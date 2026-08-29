"""Math visualization provider interface and MathVizAI (Manim) implementation."""

from __future__ import annotations

import os
import re
import shutil
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
8. Do not use external files unless ImageMobject path is provided.
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
        textbook_image_path: Optional[Path] = None,
        work_dir: Optional[Path] = None,
    ) -> VisualizationResult:
        own_dir = work_dir is None
        root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="mathviz_"))
        root.mkdir(parents=True, exist_ok=True)
        media_dir = root / "media"
        code_path = root / "scene.py"

        viz = scene_spec.get("visualization") or {}
        viz_type = viz.get("type") or scene_spec.get("scene_type") or "none"
        narration = scene_spec.get("narration") or ""
        title = scene_spec.get("title") or viz.get("title") or "Mathematics"

        # Deterministic path for simple card scenes / fallback-first types
        if viz_type in ("title_card", "summary_card", "practice", "why_explanation", "concept", "none"):
            code = self._deterministic_card(scene_spec, duration_sec)
            used_fallback = True
        elif viz_type == "textbook_page" and textbook_image_path and textbook_image_path.exists():
            code = self._textbook_page_scene(scene_spec, duration_sec, textbook_image_path)
            used_fallback = True
        elif viz_type == "algebra_steps":
            # Prefer deterministic algebra renderer for reliability; LLM can enhance if needed
            code = self._algebra_steps_scene(viz, title, duration_sec)
            used_fallback = True
        else:
            code, used_fallback = self._generate_with_self_correction(
                scene_spec, duration_sec, textbook_image_path, root
            )

        code_path.write_text(code, encoding="utf-8")
        video_path = self._run_manim(code_path, media_dir, root)

        if video_path is None:
            # Last-resort fallback
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
        textbook_image_path: Optional[Path],
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
            code = self._llm_codegen(scene_spec, duration_sec, textbook_image_path, last_error)
            code = self._strip_fences(code)
            # Syntax check
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
            last_error = err_log.read_text(encoding="utf-8", errors="ignore")[-4000:] if err_log.exists() else "render failed"
            logger.warning("Manim attempt %s failed", attempt)

        # Fallback deterministic
        return self._absolute_fallback(
            scene_spec.get("title") or "Mathematics",
            scene_spec.get("visualization") or {},
            duration_sec,
        ), True

    def _llm_codegen(
        self,
        scene_spec: dict[str, Any],
        duration_sec: float,
        textbook_image_path: Optional[Path],
        last_error: str,
    ) -> str:
        assert self.client is not None
        system = MANIM_CODEGEN_SYSTEM.format(duration=duration_sec)
        user = {
            "scene_spec": scene_spec,
            "duration_sec": duration_sec,
            "textbook_image_path": str(textbook_image_path) if textbook_image_path else None,
            "previous_error": last_error or None,
            "instruction": "Fix the previous_error if present; regenerate a correct GeneratedScene.",
        }
        import json

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
            "-ql",  # preview quality for speed; still 854x480 — we upscale/pad in ffmpeg if needed
            "--media_dir",
            str(media_dir),
            str(code_path),
            "GeneratedScene",
        ]
        # Prefer 1080p when MANIM_QUALITY=high
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
        # Pick newest
        videos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return videos[0]

    def _algebra_steps_scene(self, viz: dict[str, Any], title: str, duration: float) -> str:
        expr = viz.get("math_expression") or ""
        steps = viz.get("steps") or []
        all_steps = [expr] + [s for s in steps if s and s != expr]
        if not all_steps:
            all_steps = [title]
        # Escape for embedding in Python source via repr in template
        return FALLBACK_TEMPLATE.format(title=title, steps=all_steps, duration=max(duration, 5.0))

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
            # Split narration into short display lines
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
        # Copy image into work-relative path handled by caller — embed absolute path carefully
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
                    # Highlight rectangle in image-local normalized coords
                    w = img.width
                    h = img.height
                    rect = Rectangle(
                        width=max(0.2, {hw}) * w,
                        height=max(0.1, {hh}) * h,
                        color=YELLOW,
                        stroke_width=4,
                    )
                    # Image center is at img.get_center(); top-left relative
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


class MathVizService:
    """Facade that keeps the rest of the app provider-agnostic."""

    def __init__(self, provider: MathVizProvider | None = None) -> None:
        self.provider = provider or MathVizAIProvider()

    def render_scene(self, *args: Any, **kwargs: Any) -> VisualizationResult:
        return self.provider.render_scene(*args, **kwargs)
