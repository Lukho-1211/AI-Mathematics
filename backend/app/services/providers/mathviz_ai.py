"""Math visualization provider interface and MathVizAI (Manim) implementation."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MANIM_COLORS = frozenset(
    {"YELLOW", "TEAL", "ORANGE", "PINK", "GREEN", "BLUE", "RED", "WHITE", "PURE_BLUE"}
)


@dataclass
class VisualizationResult:
    video_path: Path
    manim_code: str
    used_fallback: bool
    duration_sec: float
    provider: str = "mathviz_ai"


class MathVizProvider(ABC):
    """Provider-agnostic interface for mathematical visualization."""

    @abstractmethod
    def render_scene(
        self,
        scene_spec: dict[str, Any],
        *,
        duration_sec: float,
        textbook_image_path: Optional[Path] = None,
        work_dir: Optional[Path] = None,
    ) -> VisualizationResult:
        raise NotImplementedError


MANIM_CODEGEN_SYSTEM = """You generate Manim Community Edition (manim CE 0.18+) Python scene code.

Rules:
1. Output ONLY valid Python code — no markdown fences.
2. Define exactly one scene class named GeneratedScene(Scene).
3. Import from manim: from manim import *
4. Use MathTex / Tex for mathematics. Prefer TransformMatchingTex for algebra steps.
5. Target duration approximately {duration} seconds using self.wait() appropriately.
6. Clean educational style: dark blue/black background, high-contrast white/yellow math.
7. Resolution-agnostic (no hardcoded pixel positions beyond Manim coords).
8. Never use ImageMobject or external image files — draw with Manim primitives only.
9. Avoid network calls, file writes outside the scene, and shell commands.
10. Keep code self-contained and syntactically valid.
"""


FALLBACK_TEMPLATE = '''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#0b1220"
        title = Text({title!r}, font_size=36, color=WHITE)
        title.to_edge(UP)
        self.play(Write(title))
        exprs = {steps!r}
        prev = None
        for i, e in enumerate(exprs):
            try:
                mob = MathTex(e, font_size=42, color=YELLOW if i == len(exprs)-1 else WHITE)
            except Exception:
                mob = Text(e, font_size=28, color=WHITE)
            mob.move_to(ORIGIN)
            if prev is None:
                self.play(Write(mob))
            else:
                self.play(TransformMatchingTex(prev, mob) if isinstance(prev, MathTex) and isinstance(mob, MathTex) else ReplacementTransform(prev, mob))
            wait_t = max(0.8, {duration} / max(1, len(exprs)))
            self.wait(wait_t)
            prev = mob
        self.wait(0.5)
'''


class MathVizAIProvider(MathVizProvider):
    """In-house MathVizAI architecture: LLM → Manim codegen → validate → self-correct → render."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.max_attempts = settings.manim_max_attempts
        self.timeout = settings.manim_timeout_sec

    def render_scene(
        self,
        scene_spec: dict[str, Any],
        *,
        duration_sec: float,
        textbook_image_path: Optional[Path] = None,  # ignored — scans never appear in video
        work_dir: Optional[Path] = None,
    ) -> VisualizationResult:
        root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="mathviz_"))
        root.mkdir(parents=True, exist_ok=True)
        media_dir = root / "media"
        code_path = root / "scene.py"

        viz = dict(scene_spec.get("visualization") or {})
        # Remap leftover textbook_page — never ImageMobject
        viz_type = (viz.get("type") or scene_spec.get("scene_type") or "none").lower()
        if viz_type in ("textbook_page", "overview", "page_overview"):
            draw0 = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
            kind = (draw0 or {}).get("kind") if draw0 else None
            viz_type = kind if kind in ("graph_2d", "geometry", "number_line", "matrix") else "concept"
            viz["type"] = viz_type
            scene_spec = {**scene_spec, "visualization": viz, "scene_type": viz_type}

        title = scene_spec.get("title") or viz.get("title") or "Mathematics"
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
        draw_kind = (draw.get("kind") if draw else None) or None

        # Prefer structured draw templates before text cards / LLM codegen
        code: Optional[str] = None
        used_fallback = True

        if draw_kind == "graph_2d" or (viz_type == "graph_2d" and draw):
            code = self._graph_2d_scene(scene_spec, duration_sec)
            used_fallback = False
        elif draw_kind == "number_line" or (viz_type == "number_line" and draw):
            code = self._number_line_scene(scene_spec, duration_sec)
            used_fallback = False
        elif draw_kind == "geometry" or (viz_type == "geometry" and draw):
            code = self._geometry_scene(scene_spec, duration_sec)
            used_fallback = False
        elif draw_kind == "matrix" or (viz_type == "matrix" and draw):
            code = self._matrix_scene(scene_spec, duration_sec)
            used_fallback = False
        elif viz_type == "graph_2d":
            code = self._graph_2d_scene(scene_spec, duration_sec)
            used_fallback = False
        elif viz_type == "number_line":
            code = self._number_line_scene(scene_spec, duration_sec)
            used_fallback = False
        elif viz_type == "geometry":
            code = self._geometry_scene(scene_spec, duration_sec)
            used_fallback = False
        elif viz_type == "matrix":
            code = self._matrix_scene(scene_spec, duration_sec)
            used_fallback = False
        elif viz_type == "algebra_steps":
            code, used_fallback = self._algebra_steps_scene(viz, title, duration_sec)
        elif viz_type in ("title_card", "summary_card", "practice", "why_explanation", "concept", "none"):
            # Prefer draw when concept/why still carries one
            if draw and draw_kind == "graph_2d":
                code = self._graph_2d_scene(scene_spec, duration_sec)
            elif draw and draw_kind == "number_line":
                code = self._number_line_scene(scene_spec, duration_sec)
            elif draw and draw_kind == "geometry":
                code = self._geometry_scene(scene_spec, duration_sec)
            elif draw and draw_kind == "matrix":
                code = self._matrix_scene(scene_spec, duration_sec)
            else:
                code = self._deterministic_card(scene_spec, duration_sec)
            used_fallback = False
        else:
            code, used_fallback = self._generate_with_self_correction(
                scene_spec, duration_sec, root
            )

        if code is None:
            code = self._absolute_fallback(title, viz, duration_sec)
            used_fallback = True

        # Hard guard: never ship ImageMobject / file paths of uploads
        if "ImageMobject" in code:
            logger.warning("Rejecting codegen with ImageMobject; using fallback")
            code = self._absolute_fallback(title, viz, duration_sec)
            used_fallback = True

        code_path.write_text(code, encoding="utf-8")
        video_path = self._run_manim(code_path, media_dir, root)

        if video_path is None:
            logger.warning("Manim render failed; using absolute fallback scene")
            code = self._absolute_fallback(title, viz, duration_sec)
            code_path.write_text(code, encoding="utf-8")
            video_path = self._run_manim(code_path, media_dir, root)
            used_fallback = True
            if video_path is None:
                raise RuntimeError("MathVizAI failed to render scene even with fallback")

        return VisualizationResult(
            video_path=video_path,
            manim_code=code,
            used_fallback=used_fallback,
            duration_sec=duration_sec,
            provider="mathviz_ai",
        )

    def _generate_with_self_correction(
        self,
        scene_spec: dict[str, Any],
        duration_sec: float,
        root: Path,
    ) -> tuple[str, bool]:
        if self.client is None:
            return self._absolute_fallback(
                scene_spec.get("title") or "Mathematics",
                scene_spec.get("visualization") or {},
                duration_sec,
            ), True

        last_error = ""
        code = ""
        for attempt in range(1, self.max_attempts + 1):
            code = self._llm_codegen(scene_spec, duration_sec, last_error)
            code = self._strip_fences(code)
            if "ImageMobject" in code:
                last_error = "Do not use ImageMobject or any external image files."
                continue
            try:
                compile(code, "<scene>", "exec")
            except SyntaxError as exc:
                last_error = f"SyntaxError: {exc}"
                logger.warning("Manim codegen attempt %s syntax error: %s", attempt, exc)
                continue

            code_path = root / f"attempt_{attempt}.py"
            code_path.write_text(code, encoding="utf-8")
            video = self._run_manim(code_path, root / "media", root)
            if video is not None:
                return code, False
            err_log = root / "manim_stderr.txt"
            last_error = (
                err_log.read_text(encoding="utf-8", errors="ignore")[-4000:]
                if err_log.exists()
                else "render failed"
            )
            logger.warning("Manim attempt %s failed", attempt)

        return self._absolute_fallback(
            scene_spec.get("title") or "Mathematics",
            scene_spec.get("visualization") or {},
            duration_sec,
        ), True

    def _llm_codegen(
        self,
        scene_spec: dict[str, Any],
        duration_sec: float,
        last_error: str,
    ) -> str:
        assert self.client is not None
        system = MANIM_CODEGEN_SYSTEM.format(duration=duration_sec)
        user = {
            "scene_spec": scene_spec,
            "duration_sec": duration_sec,
            "previous_error": last_error or None,
            "instruction": (
                "Fix the previous_error if present; regenerate a correct GeneratedScene. "
                "Never use ImageMobject. Draw with colored Manim primitives and a legend."
            ),
        }
        response = self.client.chat.completions.create(
            model=self.settings.openai_reasoning_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)},
            ],
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _strip_fences(code: str) -> str:
        code = code.strip()
        if code.startswith("```"):
            code = re.sub(r"^```(?:python)?\s*", "", code)
            code = re.sub(r"\s*```$", "", code)
        return code.strip()

    def _run_manim(self, code_path: Path, media_dir: Path, root: Path) -> Optional[Path]:
        media_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "manim",
            "render",
            "-ql",
            "--media_dir",
            str(media_dir),
            str(code_path),
            "GeneratedScene",
        ]
        if os.environ.get("MANIM_QUALITY", "low") == "high":
            cmd = [
                "manim",
                "render",
                "-qh",
                "--media_dir",
                str(media_dir),
                str(code_path),
                "GeneratedScene",
            ]

        stderr_path = root / "manim_stderr.txt"
        try:
            with open(stderr_path, "w", encoding="utf-8") as errf:
                proc = subprocess.run(
                    cmd,
                    cwd=str(root),
                    stdout=errf,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout,
                    check=False,
                )
            if proc.returncode != 0:
                logger.error("manim exited %s; see %s", proc.returncode, stderr_path)
                return None
        except FileNotFoundError:
            logger.error("manim CLI not found on PATH")
            return None
        except subprocess.TimeoutExpired:
            logger.error("manim timed out after %ss", self.timeout)
            return None

        videos = list(media_dir.rglob("*.mp4"))
        if not videos:
            return None
        videos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return videos[0]

    @staticmethod
    def _manim_color(name: str, default: str = "YELLOW") -> str:
        c = (name or default).upper()
        return c if c in _MANIM_COLORS else default

    def _graph_2d_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        """Axes + labeled series overlays and optional parameter sweep."""
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = str(draw.get("title") or scene_spec.get("title") or viz.get("title") or "Graph")
        notice = str(draw.get("notice") or "Notice how the graph changes.")
        axes = draw.get("axes") if isinstance(draw.get("axes"), dict) else {}
        x_range = draw.get("x_range") if isinstance(draw.get("x_range"), (list, tuple)) else None
        y_range = draw.get("y_range") if isinstance(draw.get("y_range"), (list, tuple)) else None
        if x_range and len(x_range) >= 2:
            x_min, x_max = float(x_range[0]), float(x_range[1])
        else:
            x_min = float(axes.get("x_min", -5))
            x_max = float(axes.get("x_max", 5))
        if y_range and len(y_range) >= 2:
            y_min, y_max = float(y_range[0]), float(y_range[1])
        else:
            y_min = float(axes.get("y_min", -5))
            y_max = float(axes.get("y_max", 5))

        series = draw.get("series") if isinstance(draw.get("series"), list) else []
        clean_series: list[dict[str, str]] = []
        for i, s in enumerate(series):
            if not isinstance(s, dict):
                continue
            expr = str(s.get("expr") or "").strip()
            if not expr or not _is_safe_embedded_expr(expr):
                continue
            clean_series.append(
                {
                    "expr": expr,
                    "label": str(s.get("label") or expr)[:40],
                    "color": self._manim_color(str(s.get("color") or "YELLOW")),
                }
            )

        sweep = draw.get("parameter_sweep") if isinstance(draw.get("parameter_sweep"), dict) else None
        sweep_family = ""
        sweep_param = "a"
        sweep_values: list[float] = []
        if sweep:
            fam = str(sweep.get("family") or "").strip()
            if fam and _is_safe_embedded_expr(fam):
                sweep_family = fam
                sweep_param = re.sub(r"[^a-zA-Z_]", "", str(sweep.get("param") or "a"))[:8] or "a"
                for v in sweep.get("values") or []:
                    try:
                        sweep_values.append(float(v))
                    except (TypeError, ValueError):
                        continue
                sweep_values = sweep_values[:6]

        if not clean_series and not sweep_family:
            # Minimal default parabola comparison
            clean_series = [
                {"expr": "x**2", "label": "a = 1", "color": "YELLOW"},
                {"expr": "-x**2", "label": "a = -1", "color": "TEAL"},
            ]

        highlights = []
        for h in draw.get("highlights") or []:
            if not isinstance(h, dict):
                continue
            pt = h.get("point")
            if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
                continue
            try:
                px, py = float(pt[0]), float(pt[1])
            except (TypeError, ValueError):
                continue
            highlights.append(
                {"point": [px, py], "label": str(h.get("label") or f"({px:g},{py:g})")[:24]}
            )

        wait_each = max(0.6, float(duration) / max(4, len(clean_series) + len(sweep_values) + 2))

        return textwrap.dedent(
            f'''
            from manim import *
            import numpy as np

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=32, color=WHITE).to_edge(UP)
                    notice = Text({notice!r}, font_size=20, color=YELLOW)
                    notice.next_to(title, DOWN, buff=0.25)
                    if notice.width > 12:
                        notice.scale_to_fit_width(12)
                    axes = Axes(
                        x_range=[{x_min}, {x_max}, 1],
                        y_range=[{y_min}, {y_max}, 1],
                        x_length=9,
                        y_length=5.2,
                        tips=False,
                        axis_config={{"color": GREY_B, "include_numbers": False}},
                    )
                    axes.next_to(notice, DOWN, buff=0.35)
                    self.play(FadeIn(title), FadeIn(notice), Create(axes), run_time=0.8)

                    series = {clean_series!r}
                    graphs = []
                    labels = VGroup()
                    for i, s in enumerate(series):
                        expr = s["expr"]
                        color = globals().get(s["color"], YELLOW)
                        def _fn(x, e=expr):
                            return float(eval(e, {{"__builtins__": {{}}}}, {{"x": x, "np": np}}))
                        try:
                            g = axes.plot(_fn, color=color, stroke_width=4)
                        except Exception:
                            continue
                        lab = Text(s["label"], font_size=18, color=color)
                        graphs.append(g)
                        labels.add(lab)
                        # Ghost previous overlays at lower opacity
                        for prev in graphs[:-1]:
                            prev.set_stroke(opacity=0.35)
                        self.play(Create(g), run_time=0.7)
                        self.wait({wait_each * 0.5})

                    if len(labels):
                        labels.arrange(RIGHT, buff=0.4)
                        labels.next_to(axes, DOWN, buff=0.2)
                        self.play(FadeIn(labels), run_time=0.4)

                    # Parameter sweep: animate successive values of the family
                    sweep_family = {sweep_family!r}
                    sweep_param = {sweep_param!r}
                    sweep_values = {sweep_values!r}
                    if sweep_family and sweep_values:
                        def make_fn(val):
                            def _fn(x, v=val, fam=sweep_family, p=sweep_param):
                                env = {{"x": x, "np": np, p: v}}
                                return float(eval(fam, {{"__builtins__": {{}}}}, env))
                            return _fn
                        param_label = Text(f"{{sweep_param}} = {{sweep_values[0]:g}}", font_size=22, color=ORANGE)
                        param_label.to_corner(UR).shift(LEFT * 0.3 + DOWN * 0.8)
                        self.play(FadeIn(param_label))
                        active = None
                        for vi, val in enumerate(sweep_values):
                            try:
                                g = axes.plot(make_fn(val), color=ORANGE, stroke_width=5)
                            except Exception:
                                continue
                            new_lab = Text(f"{{sweep_param}} = {{val:g}}", font_size=22, color=ORANGE)
                            new_lab.move_to(param_label)
                            if active is None:
                                self.play(Create(g), Transform(param_label, new_lab), run_time=0.7)
                            else:
                                self.play(
                                    ReplacementTransform(active, g),
                                    Transform(param_label, new_lab),
                                    run_time=0.8,
                                )
                            active = g
                            self.wait({wait_each})

                    # Highlights (vertex / intercepts)
                    highlights = {highlights!r}
                    for h in highlights:
                        try:
                            dot = Dot(axes.coords_to_point(h["point"][0], h["point"][1]), color=WHITE)
                            lab = Text(h["label"], font_size=18, color=WHITE).next_to(dot, UP, buff=0.15)
                            self.play(FadeIn(dot), FadeIn(lab), run_time=0.4)
                        except Exception:
                            pass

                    self.wait(0.6)
            '''
        ).strip()

    def _number_line_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = str(draw.get("title") or scene_spec.get("title") or "Number line")
        notice = str(draw.get("notice") or "Locate the marked values.")
        x_min, x_max = -5.0, 5.0
        if isinstance(draw.get("x_range"), (list, tuple)) and len(draw["x_range"]) >= 2:
            x_min, x_max = float(draw["x_range"][0]), float(draw["x_range"][1])
        else:
            x_min = float(draw.get("x_min", -5))
            x_max = float(draw.get("x_max", 5))
        points = draw.get("points") if isinstance(draw.get("points"), list) else []
        # Also accept series[{kind:point,x}] from older planners
        if not points and isinstance(draw.get("series"), list):
            for s in draw["series"]:
                if not isinstance(s, dict):
                    continue
                if (s.get("kind") or "").lower() == "point" or "x" in s or "value" in s:
                    try:
                        val = float(s.get("value", s.get("x")))
                    except (TypeError, ValueError):
                        continue
                    points.append(
                        {
                            "value": val,
                            "label": s.get("label") or f"{val:g}",
                            "color": s.get("color") or "YELLOW",
                        }
                    )
        clean_points: list[dict[str, Any]] = []
        for i, p in enumerate(points):
            if not isinstance(p, dict):
                continue
            try:
                val = float(p.get("value"))
            except (TypeError, ValueError):
                continue
            clean_points.append(
                {
                    "value": val,
                    "label": str(p.get("label") or f"{val:g}")[:24],
                    "color": self._manim_color(str(p.get("color") or "YELLOW")),
                }
            )
        wait_each = max(0.5, float(duration) / max(3, len(clean_points) + 1))

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    notice = Text({notice!r}, font_size=20, color=YELLOW)
                    notice.next_to(title, DOWN, buff=0.3)
                    if notice.width > 12:
                        notice.scale_to_fit_width(12)
                    number_line = NumberLine(
                        x_range=[{x_min}, {x_max}, 1],
                        length=10,
                        include_numbers=True,
                        color=GREY_B,
                    )
                    number_line.next_to(notice, DOWN, buff=1.0)
                    self.play(FadeIn(title), FadeIn(notice), Create(number_line))
                    points = {clean_points!r}
                    for p in points:
                        color = globals().get(p["color"], YELLOW)
                        dot = Dot(number_line.n2p(p["value"]), color=color, radius=0.12)
                        lab = Text(p["label"], font_size=22, color=color).next_to(dot, UP, buff=0.2)
                        self.play(FadeIn(dot), FadeIn(lab), run_time=0.5)
                        self.wait({wait_each})
                    self.wait(0.5)
            '''
        ).strip()

    def _geometry_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = str(draw.get("title") or scene_spec.get("title") or "Geometry")
        notice = str(draw.get("notice") or "Observe the geometric construction.")
        points = draw.get("points") if isinstance(draw.get("points"), dict) else {
            "A": [-2, -1],
            "B": [2, -1],
            "C": [0, 2],
        }
        clean_points: dict[str, list[float]] = {}
        for name, pt in points.items():
            if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
                continue
            try:
                clean_points[str(name)[:8]] = [float(pt[0]), float(pt[1])]
            except (TypeError, ValueError):
                continue
        if not clean_points:
            clean_points = {"A": [-2.0, -1.0], "B": [2.0, -1.0], "C": [0.0, 2.0]}

        segments = []
        for seg in draw.get("segments") or []:
            if isinstance(seg, (list, tuple)) and len(seg) >= 2:
                a, b = str(seg[0])[:8], str(seg[1])[:8]
                if a in clean_points and b in clean_points:
                    segments.append([a, b])
        polygons = []
        for poly in draw.get("polygons") or []:
            if isinstance(poly, (list, tuple)) and len(poly) >= 3:
                names = [str(n)[:8] for n in poly]
                if all(n in clean_points for n in names):
                    polygons.append(names)
        if not segments and not polygons:
            names = list(clean_points.keys())
            if len(names) >= 3:
                polygons = [names[:3]]
                segments = [[names[0], names[1]], [names[1], names[2]], [names[2], names[0]]]

        circles = []
        for c in draw.get("circles") or []:
            if not isinstance(c, dict):
                continue
            center = str(c.get("center") or "")[:8]
            try:
                radius = float(c.get("radius", 1))
            except (TypeError, ValueError):
                continue
            if center in clean_points and radius > 0:
                circles.append({"center": center, "radius": radius})

        wait = max(0.8, float(duration) / 4)

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    notice = Text({notice!r}, font_size=20, color=YELLOW)
                    notice.next_to(title, DOWN, buff=0.25)
                    if notice.width > 12:
                        notice.scale_to_fit_width(12)
                    self.play(FadeIn(title), FadeIn(notice))
                    pts = {clean_points!r}
                    dots = {{}}
                    labels = VGroup()
                    for name, xy in pts.items():
                        d = Dot([xy[0], xy[1], 0], color=YELLOW)
                        lab = Text(name, font_size=22, color=WHITE).next_to(d, UP, buff=0.12)
                        dots[name] = d
                        labels.add(lab)
                        self.play(FadeIn(d), FadeIn(lab), run_time=0.3)
                    for seg in {segments!r}:
                        a, b = seg[0], seg[1]
                        line = Line(dots[a].get_center(), dots[b].get_center(), color=TEAL)
                        self.play(Create(line), run_time=0.4)
                    for poly in {polygons!r}:
                        verts = [dots[n].get_center() for n in poly]
                        shape = Polygon(*verts, color=ORANGE, fill_opacity=0.15)
                        self.play(Create(shape), run_time=0.5)
                    for c in {circles!r}:
                        circ = Circle(radius=c["radius"], color=PINK).move_to(dots[c["center"]])
                        self.play(Create(circ), run_time=0.5)
                    self.wait({wait})
            '''
        ).strip()

    def _matrix_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = str(draw.get("title") or scene_spec.get("title") or "Matrix")
        notice = str(draw.get("notice") or "Compare the matrices.")
        matrix = str(draw.get("matrix") or viz.get("math_expression") or r"\begin{bmatrix}1&0\\0&1\end{bmatrix}")
        after = draw.get("after")
        # Prefer MathTex-friendly content; fall back to Text if latex-ish fails at runtime
        wait = max(1.0, float(duration) / 3)

        after_block = ""
        if after:
            after_block = f'''
                    after = None
                    try:
                        after = MathTex({str(after)!r}, font_size=40, color=TEAL)
                    except Exception:
                        after = Text({str(after)!r}, font_size=28, color=TEAL)
                    after.next_to(before, DOWN, buff=0.8)
                    self.play(TransformFromCopy(before, after), run_time=1.0)
                    self.wait({wait})
            '''

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    notice = Text({notice!r}, font_size=20, color=YELLOW)
                    notice.next_to(title, DOWN, buff=0.25)
                    if notice.width > 12:
                        notice.scale_to_fit_width(12)
                    self.play(FadeIn(title), FadeIn(notice))
                    before = None
                    try:
                        before = MathTex({matrix!r}, font_size=42, color=YELLOW)
                    except Exception:
                        before = Text({matrix!r}, font_size=28, color=YELLOW)
                    before.next_to(notice, DOWN, buff=0.6)
                    self.play(Write(before))
                    self.wait({wait})
                    {after_block}
                    self.wait(0.5)
            '''
        ).strip()

    def _algebra_steps_scene(self, viz: dict[str, Any], title: str, duration: float) -> tuple[str, bool]:
        expr = viz.get("math_expression") or ""
        steps = viz.get("steps") or []
        all_steps = [expr] + [s for s in steps if s and s != expr]
        if not all_steps:
            all_steps = [title]
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
        if draw and (draw.get("kind") or "graph_2d") == "graph_2d":
            # Structured graph beside algebra is intentional, not a fallback card
            return self._graph_2d_scene(
                {"title": title, "visualization": {"type": "graph_2d", "draw": draw, "steps": all_steps}},
                duration,
            ), False
        if draw and draw.get("kind") == "number_line":
            return (
                self._number_line_scene(
                    {"title": title, "visualization": {"type": "number_line", "draw": draw, "steps": all_steps}},
                    duration,
                ),
                False,
            )
        return FALLBACK_TEMPLATE.format(title=title, steps=all_steps, duration=max(duration, 5.0)), True

    def _deterministic_card(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        title = scene_spec.get("title") or viz.get("title") or "Lesson"
        bullets = viz.get("bullets") or []
        narration = scene_spec.get("narration") or ""
        practice_q = viz.get("practice_question")
        practice_a = viz.get("practice_answer")
        lines = bullets[:]
        if practice_q:
            lines.append(f"Q: {practice_q}")
        if practice_a:
            lines.append(f"A: {practice_a}")
        if not lines and narration:
            words = narration.split()
            chunk = []
            for w in words:
                chunk.append(w)
                if len(" ".join(chunk)) > 50:
                    lines.append(" ".join(chunk))
                    chunk = []
                    if len(lines) >= 5:
                        break
            if chunk and len(lines) < 5:
                lines.append(" ".join(chunk))

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=40, color=WHITE)
                    title.to_edge(UP)
                    self.play(FadeIn(title))
                    items = {lines!r}
                    group = VGroup()
                    for i, line in enumerate(items[:6]):
                        t = Text(line, font_size=26, color=YELLOW if i == 0 else WHITE)
                        group.add(t)
                    if len(group):
                        group.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
                        group.next_to(title, DOWN, buff=0.6)
                        group.set_x(0)
                        for t in group:
                            self.play(FadeIn(t, shift=UP*0.2), run_time=0.5)
                            self.wait(max(0.4, {duration} / max(2, len(group)+1)))
                    else:
                        self.wait({duration})
                    self.wait(0.5)
            '''
        ).strip()

    def _textbook_page_scene(
        self, scene_spec: dict[str, Any], duration: float, image_path: Path
    ) -> str:
        viz = scene_spec.get("visualization") or {}
        bbox = viz.get("highlight_bbox") or {}
        img = str(image_path).replace("\\", "/")
        hx = float(bbox.get("x", 0.1))
        hy = float(bbox.get("y", 0.1))
        hw = float(bbox.get("width", 0.8))
        hh = float(bbox.get("height", 0.2))
        title = scene_spec.get("title") or "From the textbook"
        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=32, color=WHITE).to_edge(UP)
                    img = ImageMobject(r"{img}")
                    img.set_height(5.5)
                    img.next_to(title, DOWN, buff=0.3)
                    self.play(FadeIn(title), FadeIn(img))
                    w = img.width
                    h = img.height
                    rect = Rectangle(
                        width=max(0.2, {hw}) * w,
                        height=max(0.1, {hh}) * h,
                        color=YELLOW,
                        stroke_width=4,
                    )
                    left = img.get_corner(UL)[0] + {hx} * w
                    top = img.get_corner(UL)[1] - {hy} * h
                    rect.move_to([left + rect.width/2, top - rect.height/2, 0])
                    self.play(Create(rect))
                    self.wait(max(2.0, {duration} - 2.0))
                    self.play(img.animate.scale(1.15), rect.animate.scale(1.15))
                    self.wait(1.0)
            '''
        ).strip()

    def _absolute_fallback(self, title: str, viz: dict[str, Any], duration: float) -> str:
        steps = viz.get("steps") or []
        expr = viz.get("math_expression")
        all_steps = ([expr] if expr else []) + list(steps)
        if not all_steps:
            all_steps = [title]
        return FALLBACK_TEMPLATE.format(title=title, steps=all_steps, duration=max(duration, 4.0))


def _is_safe_embedded_expr(expr: str) -> bool:
    """Allow only simple arithmetic/function expressions for embedding in Manim source."""
    if not expr or len(expr) > 100:
        return False
    lowered = expr.lower()
    banned = ("import", "exec", "eval", "open", "__", "os.", "sys.", "subprocess", ";", "lambda")
    if any(b in lowered for b in banned):
        return False
    # Characters: digits, letters, operators, parentheses, dots, spaces, asterisks
    if not re.fullmatch(r"[0-9a-zA-Z_\s\+\-\*/\.\(\),]+", expr):
        return False
    return True


class MathVizService:
    """Facade that keeps the rest of the app provider-agnostic."""

    def __init__(self, provider: MathVizProvider | None = None) -> None:
        self.provider = provider or MathVizAIProvider()

    def render_scene(self, *args: Any, **kwargs: Any) -> VisualizationResult:
        return self.provider.render_scene(*args, **kwargs)
