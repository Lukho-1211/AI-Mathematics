"""Math visualization provider interface and MathVizAI (Manim) implementation."""

from __future__ import annotations

import json
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

# Shared palette with scene planning (gold, blue, green, rose, violet)
CONCEPT_PALETTE = ["#F5C542", "#3B82F6", "#22C55E", "#F43F5E", "#A855F7"]


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
6. Clean educational style: dark blue/black background (#0b1220), high-contrast math.
7. Resolution-agnostic (no hardcoded pixel positions beyond Manim coords).
8. NEVER use ImageMobject, Image, or any external file / uploaded textbook page path.
   Only draw with Manim primitives: Axes, ParametricFunction / axes.plot, Dot, Line,
   Polygon, Circle, NumberLine, MathTex, Text, VGroup.
9. ILLUSTRATE the narration — do not only write equations. Draw graphs, diagrams, or
   number lines when the scene_spec includes visualization.draw or implies a visual.
10. Use distinct colors from visualization.draw.series (or palette gold/blue/green/rose/violet).
    Do not paint every object the same yellow/white. Show a legend when there are 2+ series.
11. Avoid network calls, file writes outside the scene, and shell commands.
12. Keep code self-contained and syntactically valid.
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
            draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
            kind = (draw or {}).get("kind") if draw else None
            viz_type = kind if kind in ("graph_2d", "geometry", "number_line") else "concept"
            viz["type"] = viz_type
            scene_spec = {**scene_spec, "visualization": viz, "scene_type": viz_type}

        title = scene_spec.get("title") or viz.get("title") or "Mathematics"
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
        draw_kind = (draw.get("kind") if draw else None) or viz_type

        code: str
        used_fallback: bool

        if viz_type in ("title_card", "summary_card", "practice", "none"):
            code = self._deterministic_card(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type in ("graph_2d",) or (draw and draw_kind == "graph_2d" and viz_type not in ("algebra_steps",)):
            code = self._graph_2d_scene(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type == "number_line" or (draw and draw_kind == "number_line" and viz_type not in ("algebra_steps",)):
            code = self._number_line_scene(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type == "geometry" or (draw and draw_kind == "geometry" and viz_type not in ("algebra_steps",)):
            code = self._geometry_scene(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type == "algebra_steps":
            code = self._algebra_steps_scene(viz, title, duration_sec)
            used_fallback = True
        elif viz_type in ("concept", "why_explanation") and draw:
            if draw_kind == "graph_2d":
                code = self._graph_2d_scene(scene_spec, duration_sec)
            elif draw_kind == "number_line":
                code = self._number_line_scene(scene_spec, duration_sec)
            elif draw_kind == "geometry":
                code = self._geometry_scene(scene_spec, duration_sec)
            else:
                code = self._deterministic_card(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type in ("concept", "why_explanation"):
            code = self._deterministic_card(scene_spec, duration_sec)
            used_fallback = True
        else:
            code, used_fallback = self._generate_with_self_correction(
                scene_spec, duration_sec, root
            )

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
            "color_palette": CONCEPT_PALETTE,
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
        quality = "-qh" if os.environ.get("MANIM_QUALITY", "low") == "high" else "-ql"
        cmd = [
            "manim",
            "render",
            quality,
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

    def _algebra_steps_scene(self, viz: dict[str, Any], title: str, duration: float) -> str:
        expr = viz.get("math_expression") or ""
        steps = viz.get("steps") or []
        all_steps = [expr] + [s for s in steps if s and s != expr]
        if not all_steps:
            all_steps = [title]

        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
        # If planner omitted draw but expression is plottable, synthesize a simple graph
        if not draw and expr:
            from app.services.understanding import _latexish_to_python, _looks_like_function

            if _looks_like_function(expr):
                py = _latexish_to_python(expr)
                if py:
                    draw = {
                        "kind": "graph_2d",
                        "x_range": [-1, 6],
                        "y_range": [-2, 8],
                        "series": [
                            {
                                "id": "curve",
                                "label": expr,
                                "expr": py,
                                "color": CONCEPT_PALETTE[0],
                            }
                        ],
                    }

        if draw and (draw.get("kind") or "graph_2d") == "graph_2d":
            return self._algebra_with_graph(title, all_steps, draw, duration)
        if draw and draw.get("kind") == "number_line":
            # Prefer number line illustration beside steps via dedicated scene
            return self._number_line_scene(
                {"title": title, "visualization": {"type": "number_line", "draw": draw, "steps": all_steps}},
                duration,
            )

        return FALLBACK_TEMPLATE.format(title=title, steps=all_steps, duration=max(duration, 5.0))

    def _algebra_with_graph(
        self, title: str, steps: list[str], draw: dict[str, Any], duration: float
    ) -> str:
        series = list(draw.get("series") or [])
        x_range = list(draw.get("x_range") or [-1, 6])
        y_range = list(draw.get("y_range") or [-2, 8])
        if len(x_range) < 2:
            x_range = [-1, 6]
        if len(y_range) < 2:
            y_range = [-2, 8]
        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=32, color=WHITE).to_edge(UP)
                    self.play(FadeIn(title))
                    axes = Axes(
                        x_range=[{x_range[0]}, {x_range[1]}, 1],
                        y_range=[{y_range[0]}, {y_range[1]}, 1],
                        x_length=5.5,
                        y_length=4.0,
                        tips=False,
                        axis_config={{"color": GREY_B, "stroke_width": 2}},
                    )
                    axes.to_edge(LEFT, buff=0.4).shift(DOWN * 0.2)
                    self.play(Create(axes), run_time=0.8)
                    series = {series!r}
                    legend_items = VGroup()
                    plotted = VGroup()
                    for i, s in enumerate(series):
                        color = s.get("color") or {CONCEPT_PALETTE!r}[i % 5]
                        kind = (s.get("kind") or "curve").lower()
                        label = s.get("label") or s.get("id") or f"s{{i}}"
                        if kind == "point":
                            x = float(s.get("x", 0))
                            y = float(s.get("y", 0))
                            try:
                                dot = Dot(axes.c2p(x, y), color=color, radius=0.1)
                            except Exception:
                                continue
                            plotted.add(dot)
                            self.play(FadeIn(dot), run_time=0.4)
                        else:
                            expr = s.get("expr")
                            if not expr:
                                continue
                            try:
                                graph = axes.plot(lambda x, e=expr: eval(e, {{"__builtins__": {{}}}}, {{"x": x}}), color=color)
                                plotted.add(graph)
                                self.play(Create(graph), run_time=1.0)
                            except Exception:
                                continue
                        swatch = Dot(color=color, radius=0.08)
                        txt = Text(str(label)[:28], font_size=18, color=color)
                        row = VGroup(swatch, txt).arrange(RIGHT, buff=0.15)
                        legend_items.add(row)
                    if len(legend_items):
                        legend_items.arrange(DOWN, aligned_edge=LEFT, buff=0.15)
                        legend_items.to_corner(UR, buff=0.35)
                        self.play(FadeIn(legend_items), run_time=0.5)
                    steps = {steps!r}
                    step_group = VGroup()
                    for i, e in enumerate(steps[:5]):
                        try:
                            mob = MathTex(e, font_size=28, color=WHITE if i < len(steps)-1 else YELLOW)
                        except Exception:
                            mob = Text(e, font_size=22, color=WHITE)
                        step_group.add(mob)
                    if len(step_group):
                        step_group.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
                        step_group.scale_to_fit_width(5.5)
                        step_group.next_to(axes, RIGHT, buff=0.4)
                        step_group.set_y(0.5)
                        wait_t = max(0.6, {duration} / max(2, len(step_group) + 2))
                        for mob in step_group:
                            self.play(FadeIn(mob, shift=RIGHT * 0.2), run_time=0.45)
                            self.wait(wait_t)
                    else:
                        self.wait(max(1.0, {duration} - 2.0))
                    self.wait(0.5)
            '''
        ).strip()

    def _graph_2d_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = scene_spec.get("title") or viz.get("title") or "Graph"
        series = list(draw.get("series") or [])
        if not series and viz.get("math_expression"):
            from app.services.understanding import _latexish_to_python

            py = _latexish_to_python(str(viz["math_expression"]))
            if py:
                series = [
                    {
                        "id": "curve",
                        "label": viz["math_expression"],
                        "expr": py,
                        "color": CONCEPT_PALETTE[0],
                    }
                ]
        if not series:
            return self._deterministic_card(scene_spec, duration)

        x_range = list(draw.get("x_range") or [-2, 6])
        y_range = list(draw.get("y_range") or [-4, 8])
        if len(x_range) < 2:
            x_range = [-2, 6]
        if len(y_range) < 2:
            y_range = [-4, 8]
        bullets = viz.get("bullets") or []

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    self.play(FadeIn(title))
                    axes = Axes(
                        x_range=[{float(x_range[0])}, {float(x_range[1])}, 1],
                        y_range=[{float(y_range[0])}, {float(y_range[1])}, 1],
                        x_length=9,
                        y_length=5.2,
                        tips=False,
                        axis_config={{"color": GREY_B, "stroke_width": 2}},
                    )
                    axes.next_to(title, DOWN, buff=0.35)
                    self.play(Create(axes), run_time=0.9)
                    series = {series!r}
                    legend_items = VGroup()
                    for i, s in enumerate(series):
                        color = s.get("color") or {CONCEPT_PALETTE!r}[i % 5]
                        kind = (s.get("kind") or "curve").lower()
                        label = s.get("label") or s.get("id") or f"s{{i}}"
                        if kind == "point":
                            x = float(s.get("x", 0))
                            y = float(s.get("y", 0))
                            try:
                                dot = Dot(axes.c2p(x, y), color=color, radius=0.12)
                                lab = Text(str(label)[:20], font_size=20, color=color)
                                lab.next_to(dot, UP, buff=0.12)
                                self.play(FadeIn(dot), FadeIn(lab), run_time=0.5)
                            except Exception:
                                pass
                        else:
                            expr = s.get("expr")
                            if expr:
                                try:
                                    graph = axes.plot(
                                        lambda x, e=expr: eval(e, {{"__builtins__": {{}}}}, {{"x": x}}),
                                        color=color,
                                        stroke_width=4,
                                    )
                                    self.play(Create(graph), run_time=1.2)
                                except Exception:
                                    pass
                        swatch = Dot(color=color, radius=0.08)
                        txt = Text(str(label)[:32], font_size=18, color=color)
                        legend_items.add(VGroup(swatch, txt).arrange(RIGHT, buff=0.15))
                    if len(legend_items) >= 1:
                        legend_items.arrange(DOWN, aligned_edge=LEFT, buff=0.12)
                        legend_items.to_corner(UR, buff=0.3)
                        self.play(FadeIn(legend_items), run_time=0.4)
                    bullets = {bullets!r}
                    if bullets:
                        bg = VGroup(*[Text(str(b)[:50], font_size=20, color=WHITE) for b in bullets[:3]])
                        bg.arrange(DOWN, aligned_edge=LEFT)
                        bg.to_edge(DOWN, buff=0.3)
                        self.play(FadeIn(bg), run_time=0.5)
                    self.wait(max(1.5, {duration} - 3.5))
            '''
        ).strip()

    def _number_line_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = scene_spec.get("title") or viz.get("title") or "Number line"
        series = list(draw.get("series") or [])
        x_range = list(draw.get("x_range") or [-5, 5])
        if len(x_range) < 2:
            x_range = [-5, 5]
        if not series:
            series = [
                {
                    "id": "p0",
                    "label": "0",
                    "kind": "point",
                    "x": 0,
                    "color": CONCEPT_PALETTE[0],
                }
            ]

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    self.play(FadeIn(title))
                    x0, x1 = {float(x_range[0])}, {float(x_range[1])}
                    nline = NumberLine(
                        x_range=[x0, x1, 1],
                        length=10,
                        include_numbers=True,
                        color=GREY_B,
                    )
                    nline.next_to(title, DOWN, buff=1.2)
                    self.play(Create(nline), run_time=0.9)
                    series = {series!r}
                    legend_items = VGroup()
                    for i, s in enumerate(series):
                        color = s.get("color") or {CONCEPT_PALETTE!r}[i % 5]
                        kind = (s.get("kind") or "point").lower()
                        label = s.get("label") or s.get("id") or f"s{{i}}"
                        if kind in ("interval", "ray", "segment"):
                            a = float(s.get("x_min", s.get("x", x0)))
                            b = float(s.get("x_max", s.get("x2", x1)))
                            try:
                                start = nline.n2p(a)
                                end = nline.n2p(b)
                                line = Line(start, end, color=color, stroke_width=8)
                                self.play(Create(line), run_time=0.7)
                            except Exception:
                                pass
                        else:
                            x = float(s.get("x", 0))
                            try:
                                dot = Dot(nline.n2p(x), color=color, radius=0.14)
                                lab = Text(str(label)[:24], font_size=22, color=color)
                                lab.next_to(dot, UP, buff=0.25)
                                self.play(FadeIn(dot), FadeIn(lab), run_time=0.5)
                            except Exception:
                                pass
                        swatch = Dot(color=color, radius=0.08)
                        txt = Text(str(label)[:32], font_size=18, color=color)
                        legend_items.add(VGroup(swatch, txt).arrange(RIGHT, buff=0.15))
                    if len(legend_items):
                        legend_items.arrange(DOWN, aligned_edge=LEFT, buff=0.15)
                        legend_items.to_edge(DOWN, buff=0.6)
                        self.play(FadeIn(legend_items), run_time=0.4)
                    self.wait(max(1.5, {duration} - 3.0))
            '''
        ).strip()

    def _geometry_scene(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else {}
        title = scene_spec.get("title") or viz.get("title") or "Geometry"
        shapes = list(draw.get("shapes") or [])
        series = list(draw.get("series") or [])
        if not shapes:
            # Build from series labels as a default triangle
            shapes = [
                {
                    "id": "tri",
                    "kind": "polygon",
                    "points": [[-2.5, -1.5], [2.5, -1.5], [0, 2.2]],
                    "label": (series[0].get("label") if series else title)[:30],
                    "color": (series[0].get("color") if series else CONCEPT_PALETTE[0]),
                }
            ]

        return textwrap.dedent(
            f'''
            from manim import *

            class GeneratedScene(Scene):
                def construct(self):
                    self.camera.background_color = "#0b1220"
                    title = Text({title!r}, font_size=34, color=WHITE).to_edge(UP)
                    self.play(FadeIn(title))
                    shapes = {shapes!r}
                    legend_items = VGroup()
                    for i, sh in enumerate(shapes):
                        color = sh.get("color") or {CONCEPT_PALETTE!r}[i % 5]
                        kind = (sh.get("kind") or "polygon").lower()
                        label = sh.get("label") or sh.get("id") or f"s{{i}}"
                        mob = None
                        if kind == "circle":
                            r = float(sh.get("radius", 1.5))
                            c = sh.get("center") or [0, 0]
                            mob = Circle(radius=r, color=color, stroke_width=4)
                            mob.move_to([float(c[0]), float(c[1]), 0])
                        elif kind == "segment" or kind == "line":
                            pts = sh.get("points") or [[-2, 0], [2, 0]]
                            mob = Line(
                                [float(pts[0][0]), float(pts[0][1]), 0],
                                [float(pts[1][0]), float(pts[1][1]), 0],
                                color=color,
                                stroke_width=4,
                            )
                        else:
                            pts = sh.get("points") or [[-2, -1], [2, -1], [0, 2]]
                            verts = [[float(p[0]), float(p[1]), 0] for p in pts]
                            mob = Polygon(*verts, color=color, stroke_width=4)
                        if mob is not None:
                            self.play(Create(mob), run_time=0.9)
                            lab = Text(str(label)[:28], font_size=22, color=color)
                            lab.next_to(mob, DOWN, buff=0.25)
                            self.play(FadeIn(lab), run_time=0.35)
                        swatch = Dot(color=color, radius=0.08)
                        txt = Text(str(label)[:32], font_size=18, color=color)
                        legend_items.add(VGroup(swatch, txt).arrange(RIGHT, buff=0.15))
                    if len(legend_items) >= 2:
                        legend_items.arrange(DOWN, aligned_edge=LEFT, buff=0.12)
                        legend_items.to_corner(UR, buff=0.35)
                        self.play(FadeIn(legend_items), run_time=0.4)
                    self.wait(max(1.5, {duration} - 3.0))
            '''
        ).strip()

    def _deterministic_card(self, scene_spec: dict[str, Any], duration: float) -> str:
        viz = scene_spec.get("visualization") or {}
        title = scene_spec.get("title") or viz.get("title") or "Lesson"
        bullets = viz.get("bullets") or []
        narration = scene_spec.get("narration") or ""
        practice_q = viz.get("practice_question")
        practice_a = viz.get("practice_answer")
        lines = list(bullets)
        if practice_q:
            lines.append(f"Q: {practice_q}")
        if practice_a:
            lines.append(f"A: {practice_a}")
        if not lines and narration:
            words = narration.split()
            chunk: list[str] = []
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

    def _absolute_fallback(self, title: str, viz: dict[str, Any], duration: float) -> str:
        steps = viz.get("steps") or []
        expr = viz.get("math_expression")
        all_steps = ([expr] if expr else []) + list(steps)
        if not all_steps:
            all_steps = [title]
        return FALLBACK_TEMPLATE.format(title=title, steps=all_steps, duration=max(duration, 4.0))


class MathVizService:
    """Facade that keeps the rest of the app provider-agnostic."""

    def __init__(self, provider: MathVizProvider | None = None) -> None:
        self.provider = provider or MathVizAIProvider()

    def render_scene(self, *args: Any, **kwargs: Any) -> VisualizationResult:
        return self.provider.render_scene(*args, **kwargs)
