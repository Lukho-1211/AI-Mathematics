"""LLM-based mathematical understanding, lesson planning, scripting, and scene specs."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Optional

import sympy as sp
from openai import OpenAI
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.quality import _debug_agent_log

logger = get_logger(__name__)

# Safe symbols for expression parsing (no arbitrary Python eval).
_SAFE_LOCALS: dict[str, Any] = {
    "x": sp.symbols("x"),
    "y": sp.symbols("y"),
    "t": sp.symbols("t"),
    "a": sp.symbols("a"),
    "b": sp.symbols("b"),
    "c": sp.symbols("c"),
    "h": sp.symbols("h"),
    "k": sp.symbols("k"),
    "n": sp.symbols("n"),
    "pi": sp.pi,
    "e": sp.E,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "sqrt": sp.sqrt,
    "Abs": sp.Abs,
    "abs": sp.Abs,
}

_DRAWABLE_TYPES = frozenset(
    {"graph_2d", "geometry", "number_line", "matrix", "algebra_steps"}
)
_REMAP_FROM = frozenset({"concept", "why_explanation", "none", "custom"})
_TEXTBOOK_PAGE_TYPES = frozenset({"textbook_page", "overview", "page_overview"})
_SERIES_COLORS = ("YELLOW", "TEAL", "ORANGE", "PINK", "GREEN", "BLUE", "RED", "WHITE")


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_reasoning_model

    def json_completion(self, system: str, user: str, temperature: float = 0.2) -> dict[str, Any]:
        if not self.settings.openai_api_key or self.settings.openai_api_key.startswith("sk-your-"):
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. Set a real key in .env and restart api/worker."
            )
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON from LLM: %s", content[:800])
            raise ValueError("LLM returned invalid JSON") from exc


class MathUnderstandingService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def analyze(self, page_content: dict[str, Any]) -> dict[str, Any]:
        system = """You are an expert mathematics educator and curriculum designer.
Analyze AUTHORITATIVE textbook page(s) content that has already been OCR'd and human-reviewed.

Rules:
- Distinguish CONTENT FOUND ON PAGE(S) from AI EXPLANATION.
- Never invent equations, numbers, or definitions not present on the page(s).
- If something is ambiguous, mark it under "uncertainties" instead of guessing.
- Treat multi-page content as one continuous lesson when page_location spans multiple pages.
- Treat coefficients, parameters, transformations, intercepts, vertices, slopes, and geometric
  relations as visualization-required. Fill "steps_needing_visualization" aggressively whenever
  a graph, number line, diagram, or animated parameter change would help a student see the math.
- Return structured JSON only."""

        user = f"""Analyze this reviewed textbook page(s) content and return JSON:
{{
  "topic": "...",
  "concepts": ["..."],
  "equations_meaning": [{{"latex": "...", "meaning": "...", "source_id": "..."}}],
  "intended_teaching_sequence": ["..."],
  "examples_to_explain": ["..."],
  "steps_needing_visualization": ["..."],
  "prerequisites": ["..."],
  "learner_should_understand": ["..."],
  "uncertainties": ["..."],
  "difficulty_level": "middle_school|high_school|undergraduate|advanced"
}}

PAGE CONTENT (authoritative):
{json.dumps(page_content, indent=2)}
"""
        return self.llm.json_completion(system, user, temperature=0.1)


class LessonPlanService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def create(self, understanding: dict[str, Any], page_content: dict[str, Any]) -> dict[str, Any]:
        system = """You create concise, pedagogically sound lesson plans for short educational videos
(3–8 minutes) explaining textbook page(s). Return JSON only. Do not invent page content.

Visualization rule (Explain → Visualize → Connect):
- Prefer visualization_candidates of type graph_2d, number_line, geometry, or algebra_steps
  whenever the page has a function, coefficient/parameter change, number line, figure, or
  worked algebraic steps.
- Use type "none" only when nothing drawable exists.
- For functions like y = ax^2 + bx + c, plan separate candidates for a (direction/width),
  b/h (horizontal shift), and c/k (vertical shift) when those parameters matter."""

        user = f"""Create a lesson plan JSON:
{{
  "topic": "...",
  "learning_objectives": ["..."],
  "concepts": ["..."],
  "prerequisites": ["..."],
  "sections": [{{"title": "...", "duration": 20, "purpose": "..."}}],
  "teaching_sequence": ["..."],
  "visualization_candidates": [
    {{"reason": "...", "type": "algebra_steps|graph_2d|geometry|number_line|matrix|none", "math_expression": "..."}}
  ]
}}

UNDERSTANDING:
{json.dumps(understanding, indent=2)}

PAGE CONTENT:
{json.dumps(page_content, indent=2)}
"""
        return self.llm.json_completion(system, user, temperature=0.2)


class ScriptService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def generate(
        self,
        lesson_plan: dict[str, Any],
        understanding: dict[str, Any],
        page_content: dict[str, Any],
        language: str = "en",
    ) -> dict[str, Any]:
        system = f"""You write professional teacher-style narration for mathematics explanation videos.
Language: {language}.

Pedagogy: Explain → Visualize → Connect.
- State the idea clearly, then narrate what the student should SEE on the visualization,
  then connect the visual back to the mathematics.
- When discussing a coefficient or parameter (e.g. a, b, c, h, k), say what changes on the
  graph (opens up/down, narrower/wider, shifts left/right/up/down) — do not describe only in words.
- Example: "Notice that when a changes from positive to negative, the parabola reflects across the x-axis."

Rules:
- Explain WHY each step is performed. Never merely describe what is on the page.
- Use examples from the uploaded page(s) only.
- Highlight common mistakes.
- Keep language clear for the learner's level.
- Structure into the standard 8 scenes when appropriate:
  1 title, 2 topic overview (restate the problem in clean math — NEVER show a scanned page),
  3 concept, 4 worked example, 5 why explanation,
  6 additional visualization (graph/diagram/number line), 7 summary, 8 practice question.
- Do NOT use scene_type "textbook_page". For overview use "concept" or "graph_2d".
- Scenes 3, 5, and 6 should use scene_type graph_2d / number_line / geometry / algebra_steps
  whenever the topic involves functions, transformations, or diagrams — not text-only concept cards.
- Set needs_visualization=true whenever MathViz can draw the idea.
- Do NOT hallucinate mathematics. If unsure, omit rather than invent.
Return JSON only."""

        user = f"""Generate narration script JSON:
{{
  "full_script": "concatenated narration",
  "segments": [
    {{
      "scene_id": "scene_01",
      "title": "Title",
      "scene_type": "title_card|concept|algebra_steps|why_explanation|summary_card|practice|graph_2d|geometry|number_line|matrix|custom",
      "narration": "...",
      "duration_estimate": 20,
      "needs_visualization": true,
      "source_expression_ids": []
    }}
  ]
}}

LESSON PLAN:
{json.dumps(lesson_plan, indent=2)}

UNDERSTANDING:
{json.dumps(understanding, indent=2)}

PAGE CONTENT:
{json.dumps(page_content, indent=2)}
"""
        return self.llm.json_completion(system, user, temperature=0.35)


class SceneSpecService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def generate(
        self,
        script: dict[str, Any],
        lesson_plan: dict[str, Any],
        page_content: dict[str, Any],
    ) -> list[dict[str, Any]]:
        system = """You convert a mathematics video script into structured scene specifications
for a MathVizAI-style Manim visualization engine.

Core rule (Explain → Visualize → Connect):
- If a variable, coefficient, parameter, transformation, intercept, vertex, or relationship
  can be drawn, you MUST emit a visualization with a structured "draw" object.
- Text-only types (none / bullets-only concept cards) are allowed ONLY for title_card,
  summary_card, and practice scenes.
- Prefer showing CHANGE: multiple series overlays or a parameter_sweep so the student sees
  cause and effect (e.g. a=1 vs a=-1), not only a final static graph.

Rules:
- For algebra, include explicit step arrays that must be mathematically correct.
- visualization.type must be one of:
  title_card, algebra_steps, graph_2d, geometry, number_line,
  matrix, concept, why_explanation, summary_card, practice, none
- NEVER use textbook_page or highlight_bbox — scanned page images are never shown in video.
- Function expressions in draw.series[].expr and draw.parameter_sweep.family must use
  Python/SymPy syntax with ** for powers (e.g. "a * x**2", "x**2 - 5*x + 6"), variable x.
- draw.series[].color must be a Manim color name: YELLOW, TEAL, ORANGE, PINK, GREEN, BLUE, RED, WHITE.
Return JSON: {"scenes": [...]}"""

        user = f"""Produce scene specs JSON:
{{
  "scenes": [
    {{
      "scene_id": "scene_01",
      "order_index": 0,
      "title": "Effect of a",
      "duration": 25,
      "narration": "Notice that when a changes from positive to negative, the parabola reflects.",
      "scene_type": "graph_2d",
      "visualization": {{
        "type": "graph_2d",
        "math_expression": "y = a x^2",
        "steps": [],
        "highlight_bbox": null,
        "title": "Effect of a",
        "bullets": [],
        "practice_question": null,
        "practice_answer": null,
        "draw": {{
          "kind": "graph_2d",
          "title": "Effect of a",
          "notice": "When a changes sign, the parabola reflects across the x-axis.",
          "axes": {{"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5}},
          "series": [
            {{"expr": "x**2", "label": "a = 1", "color": "YELLOW"}},
            {{"expr": "-x**2", "label": "a = -1", "color": "TEAL"}}
          ],
          "highlights": [{{"kind": "vertex", "point": [0, 0], "label": "(0, 0)"}}],
          "parameter_sweep": {{
            "param": "a",
            "family": "a * x**2",
            "values": [1, 2, 0.5, -1]
          }}
        }}
      }}
    }},
    {{
      "scene_id": "scene_02",
      "order_index": 1,
      "title": "Worked example",
      "duration": 25,
      "narration": "...",
      "scene_type": "algebra_steps",
      "visualization": {{
        "type": "algebra_steps",
        "math_expression": "x^2 - 5x + 6 = 0",
        "steps": ["(x-2)(x-3)=0", "x=2 or x=3"],
        "title": "Solve",
        "bullets": [],
        "draw": null
      }}
    }}
  ]
}}

SCRIPT:
{json.dumps(script, indent=2)}

LESSON PLAN:
{json.dumps(lesson_plan, indent=2)}

PAGE CONTENT:
{json.dumps(page_content, indent=2)}
"""
        data = self.llm.json_completion(system, user, temperature=0.2)
        scenes = data.get("scenes") or []
        for i, s in enumerate(scenes):
            s["order_index"] = s.get("order_index", i)
            if "visualization" not in s:
                s["visualization"] = {"type": "none"}
        # #region agent log
        _raw = []
        for s in scenes:
            viz = s.get("visualization") if isinstance(s.get("visualization"), dict) else {}
            _raw.append(
                {
                    "scene_id": s.get("scene_id"),
                    "scene_type": s.get("scene_type"),
                    "viz_type": viz.get("type"),
                    "viz_keys": list(viz.keys())[:16],
                    "expr_type": type(viz.get("math_expression")).__name__,
                    "expr": str(viz.get("math_expression"))[:160] if viz.get("math_expression") is not None else None,
                    "steps_n": len(viz.get("steps") or []) if isinstance(viz.get("steps"), list) else 0,
                    "scene_expr": str(s.get("math_expression"))[:80] if s.get("math_expression") is not None else None,
                }
            )
        _debug_agent_log("A", "understanding.py:SceneSpecService.generate", "raw_llm_scenes", {"count": len(scenes), "scenes": _raw})
        # #endregion
        return sanitize_scenes(scenes)


# ---------------------------------------------------------------------------
# Scene sanitization + SymPy-safe draw payloads
# ---------------------------------------------------------------------------


def sanitize_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize scene specs so MathViz can render without guessing."""
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(scenes or []):
        scene = copy.deepcopy(raw)
        scene["order_index"] = int(scene.get("order_index", i))
        viz = scene.get("visualization")
        if not isinstance(viz, dict):
            viz = {}
            scene["visualization"] = viz

        scene_type = (scene.get("scene_type") or viz.get("type") or "custom").strip()
        viz_type = (viz.get("type") or scene_type or "none").strip()

        # Never show scanned textbook pages in video specs
        viz.pop("highlight_bbox", None)
        if scene_type.lower() in _TEXTBOOK_PAGE_TYPES or viz_type.lower() in _TEXTBOOK_PAGE_TYPES:
            inferred = _infer_drawable_kind(scene, viz)
            if inferred:
                scene_type = inferred
                viz_type = inferred
            else:
                scene_type = "concept"
                viz_type = "concept"

        # Align types
        if viz_type in ("", "none") and scene_type not in ("", "none"):
            viz_type = scene_type
        viz["type"] = viz_type
        scene["scene_type"] = scene_type if scene_type else viz_type

        draw = viz.get("draw")
        if not isinstance(draw, dict):
            draw = None

        # Remap text-ish scenes that clearly need a graph / number line / geometry
        if viz_type in _REMAP_FROM or scene_type in _REMAP_FROM:
            inferred = _infer_drawable_kind(scene, viz)
            if inferred:
                viz_type = inferred
                viz["type"] = inferred
                scene["scene_type"] = inferred

        if viz_type in _DRAWABLE_TYPES:
            if viz_type == "algebra_steps":
                viz["steps"] = _coerce_steps(viz.get("steps"))
                recovered = _algebra_expression_from_viz(viz)
                if recovered:
                    viz["math_expression"] = recovered
                # Algebra keeps steps; optional draw is fine but not required
                if draw:
                    viz["draw"] = _sanitize_draw(draw, fallback_kind="algebra_steps", scene=scene, viz=viz)
            else:
                sanitized = _sanitize_draw(
                    draw or {},
                    fallback_kind=viz_type,
                    scene=scene,
                    viz=viz,
                )
                if sanitized:
                    viz["draw"] = sanitized
                elif viz_type == "graph_2d":
                    # Last-resort: try to build from math_expression
                    built = _build_graph_draw_from_expression(viz, scene)
                    if built:
                        viz["draw"] = built
                    else:
                        # Cannot draw — demote to concept card rather than broken graph
                        logger.warning(
                            "Scene %s graph_2d missing usable draw; demoting to concept",
                            scene.get("scene_id"),
                        )
                        viz["type"] = "concept"
                        scene["scene_type"] = "concept"
                        viz.pop("draw", None)

        out.append(scene)
    return out


def _infer_drawable_kind(scene: dict[str, Any], viz: dict[str, Any]) -> Optional[str]:
    draw = viz.get("draw") if isinstance(viz.get("draw"), dict) else None
    if draw:
        kind = (draw.get("kind") or "").strip()
        if kind in _DRAWABLE_TYPES:
            return kind

    blob = " ".join(
        str(x)
        for x in (
            scene.get("title"),
            scene.get("narration"),
            viz.get("title"),
            viz.get("math_expression"),
            " ".join(viz.get("bullets") or []),
        )
        if x
    ).lower()

    if any(k in blob for k in ("number line", "numberline", "real line", "interval")):
        return "number_line"
    if any(k in blob for k in ("matrix", "determinant", "row reduce")):
        return "matrix"
    if any(k in blob for k in ("triangle", "circle", "polygon", "geometry", "angle", "perpendicular")):
        return "geometry"
    if any(
        k in blob
        for k in (
            "parabola",
            "graph",
            "function",
            "plot",
            "quadratic",
            "linear",
            "coefficient",
            "opens upward",
            "opens downward",
            "vertex",
            "intercept",
            "transformation",
            "shift",
            "reflect",
            "ax^2",
            "a x^2",
            "y =",
            "f(x)",
        )
    ):
        return "graph_2d"
    if viz.get("math_expression") and _looks_like_function(str(viz.get("math_expression"))):
        return "graph_2d"
    return None


def _coerce_steps(steps: Any) -> list[str]:
    if isinstance(steps, str) and steps.strip():
        return [steps.strip()]
    if not isinstance(steps, list):
        return []
    out: list[str] = []
    for item in steps:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif item is not None and item != "":
            out.append(str(item))
    return out


def _algebra_expression_from_viz(viz: dict[str, Any]) -> str:
    expr = viz.get("math_expression")
    if isinstance(expr, str) and expr.strip():
        return expr.strip()
    if isinstance(expr, list):
        for item in expr:
            if isinstance(item, str) and item.strip():
                return item.strip()
    for step in viz.get("steps") or []:
        if isinstance(step, str) and step.strip():
            return step.strip()
    return ""


def _looks_like_function(expr: str) -> bool:
    e = expr.lower().replace(" ", "")
    if "y=" in e or "f(x)" in e or "f =" in e:
        return True
    if re.search(r"x\s*\*\*\s*\d|x\s*\^\s*\d|x\d", e):
        return True
    return False


def _sanitize_draw(
    draw: dict[str, Any],
    *,
    fallback_kind: str,
    scene: dict[str, Any],
    viz: dict[str, Any],
) -> Optional[dict[str, Any]]:
    kind = (draw.get("kind") or fallback_kind or "").strip()
    if kind not in _DRAWABLE_TYPES:
        kind = fallback_kind

    if kind == "graph_2d":
        return _sanitize_graph_draw(draw, scene=scene, viz=viz)
    if kind == "number_line":
        return _sanitize_number_line_draw(draw, scene=scene, viz=viz)
    if kind == "geometry":
        return _sanitize_geometry_draw(draw, scene=scene, viz=viz)
    if kind == "matrix":
        return _sanitize_matrix_draw(draw, scene=scene, viz=viz)
    if kind == "algebra_steps":
        return None
    return None


def _sanitize_graph_draw(
    draw: dict[str, Any],
    *,
    scene: dict[str, Any],
    viz: dict[str, Any],
) -> Optional[dict[str, Any]]:
    axes = draw.get("axes") if isinstance(draw.get("axes"), dict) else {}
    x_min = float(axes.get("x_min", -5))
    x_max = float(axes.get("x_max", 5))
    y_min = float(axes.get("y_min", -5))
    y_max = float(axes.get("y_max", 5))
    if x_min >= x_max:
        x_min, x_max = -5.0, 5.0
    if y_min >= y_max:
        y_min, y_max = -5.0, 5.0

    series_out: list[dict[str, Any]] = []
    raw_series = draw.get("series") if isinstance(draw.get("series"), list) else []
    for i, s in enumerate(raw_series):
        if not isinstance(s, dict):
            continue
        expr_raw = s.get("expr") or s.get("expression") or ""
        safe = safe_parse_function(str(expr_raw))
        if not safe:
            continue
        color = str(s.get("color") or _SERIES_COLORS[i % len(_SERIES_COLORS)]).upper()
        if color not in _SERIES_COLORS:
            color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        series_out.append(
            {
                "expr": safe["expr"],
                "label": str(s.get("label") or safe["expr"])[:48],
                "color": color,
            }
        )

    sweep_out = None
    raw_sweep = draw.get("parameter_sweep") if isinstance(draw.get("parameter_sweep"), dict) else None
    if raw_sweep:
        family_raw = str(raw_sweep.get("family") or "")
        param = str(raw_sweep.get("param") or "a").strip() or "a"
        values = raw_sweep.get("values") or []
        if not isinstance(values, list):
            values = []
        clean_values: list[float] = []
        for v in values:
            try:
                clean_values.append(float(v))
            except (TypeError, ValueError):
                continue
        family_safe = safe_parse_function(family_raw, extra_symbols=[param])
        if family_safe and clean_values:
            # Expand sweep into series if we have few overlays
            sweep_out = {
                "param": param,
                "family": family_safe["expr"],
                "values": clean_values[:8],
            }
            if len(series_out) < 2:
                for j, val in enumerate(clean_values[:4]):
                    substituted = safe_substitute_param(family_safe["expr"], param, val)
                    if not substituted:
                        continue
                    series_out.append(
                        {
                            "expr": substituted,
                            "label": f"{param} = {val:g}",
                            "color": _SERIES_COLORS[j % len(_SERIES_COLORS)],
                        }
                    )

    if not series_out:
        built = _build_graph_draw_from_expression(viz, scene)
        if built:
            series_out = built.get("series") or []
            if not draw.get("notice"):
                draw = {**draw, "notice": built.get("notice")}
            if not draw.get("title"):
                draw = {**draw, "title": built.get("title")}

    if not series_out:
        return None

    highlights: list[dict[str, Any]] = []
    for h in draw.get("highlights") or []:
        if not isinstance(h, dict):
            continue
        point = h.get("point")
        if not (isinstance(point, (list, tuple)) and len(point) >= 2):
            continue
        try:
            px, py = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        highlights.append(
            {
                "kind": str(h.get("kind") or "point"),
                "point": [px, py],
                "label": str(h.get("label") or f"({px:g}, {py:g})")[:32],
            }
        )

    notice = str(
        draw.get("notice")
        or scene.get("narration")
        or "Compare the curves and notice how the parameter changes the graph."
    )[:200]
    title = str(draw.get("title") or viz.get("title") or scene.get("title") or "Graph")[:80]

    result: dict[str, Any] = {
        "kind": "graph_2d",
        "title": title,
        "notice": notice,
        "axes": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
        "series": series_out[:6],
        "highlights": highlights[:6],
    }
    if sweep_out:
        result["parameter_sweep"] = sweep_out
    return result


def _build_graph_draw_from_expression(
    viz: dict[str, Any], scene: dict[str, Any]
) -> Optional[dict[str, Any]]:
    expr = str(viz.get("math_expression") or "")
    rhs = _extract_rhs(expr)
    safe = safe_parse_function(rhs or expr)
    if not safe:
        # Quadratic defaults for pedagogy when page is about quadratics
        blob = f"{scene.get('title', '')} {scene.get('narration', '')} {expr}".lower()
        if "quadratic" in blob or "parabola" in blob or "ax^2" in blob.replace(" ", ""):
            return {
                "kind": "graph_2d",
                "title": str(scene.get("title") or "Parabola"),
                "notice": "When a changes sign, the parabola reflects across the x-axis.",
                "axes": {"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5},
                "series": [
                    {"expr": "x**2", "label": "a = 1", "color": "YELLOW"},
                    {"expr": "-x**2", "label": "a = -1", "color": "TEAL"},
                ],
                "highlights": [{"kind": "vertex", "point": [0, 0], "label": "(0, 0)"}],
                "parameter_sweep": {
                    "param": "a",
                    "family": "a * x**2",
                    "values": [1, 2, 0.5, -1],
                },
            }
        return None
    return {
        "kind": "graph_2d",
        "title": str(viz.get("title") or scene.get("title") or "Graph"),
        "notice": str(scene.get("narration") or "Observe the graph of this function.")[:200],
        "axes": {"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5},
        "series": [{"expr": safe["expr"], "label": safe["expr"], "color": "YELLOW"}],
        "highlights": [],
    }


def _sanitize_number_line_draw(
    draw: dict[str, Any],
    *,
    scene: dict[str, Any],
    viz: dict[str, Any],
) -> dict[str, Any]:
    points_out: list[dict[str, Any]] = []
    for i, p in enumerate(draw.get("points") or []):
        if isinstance(p, (int, float)):
            points_out.append({"value": float(p), "label": str(p), "color": _SERIES_COLORS[i % len(_SERIES_COLORS)]})
            continue
        if not isinstance(p, dict):
            continue
        try:
            val = float(p.get("value"))
        except (TypeError, ValueError):
            continue
        color = str(p.get("color") or _SERIES_COLORS[i % len(_SERIES_COLORS)]).upper()
        if color not in _SERIES_COLORS:
            color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        points_out.append(
            {
                "value": val,
                "label": str(p.get("label") or f"{val:g}")[:24],
                "color": color,
            }
        )

    # Try to extract roots from algebra expression / steps
    if not points_out:
        for step in [viz.get("math_expression"), *(viz.get("steps") or [])]:
            if not step:
                continue
            for m in re.finditer(r"(?i)\bx\s*=\s*([-+]?\d+(?:\.\d+)?)", str(step)):
                val = float(m.group(1))
                points_out.append(
                    {
                        "value": val,
                        "label": f"x={val:g}",
                        "color": _SERIES_COLORS[len(points_out) % len(_SERIES_COLORS)],
                    }
                )

    x_min = float(draw.get("x_min", -5))
    x_max = float(draw.get("x_max", 5))
    if points_out:
        vals = [p["value"] for p in points_out]
        pad = 2
        x_min = min(x_min, min(vals) - pad)
        x_max = max(x_max, max(vals) + pad)
    if x_min >= x_max:
        x_min, x_max = -5.0, 5.0

    return {
        "kind": "number_line",
        "title": str(draw.get("title") or viz.get("title") or scene.get("title") or "Number line")[:80],
        "notice": str(draw.get("notice") or scene.get("narration") or "Locate the marked values.")[:200],
        "x_min": x_min,
        "x_max": x_max,
        "points": points_out[:8],
    }


def _sanitize_geometry_draw(
    draw: dict[str, Any],
    *,
    scene: dict[str, Any],
    viz: dict[str, Any],
) -> dict[str, Any]:
    points: dict[str, list[float]] = {}
    for name, pt in (draw.get("points") or {}).items() if isinstance(draw.get("points"), dict) else []:
        if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
            continue
        try:
            points[str(name)[:8]] = [float(pt[0]), float(pt[1])]
        except (TypeError, ValueError):
            continue

    segments: list[list[str]] = []
    for seg in draw.get("segments") or []:
        if isinstance(seg, (list, tuple)) and len(seg) >= 2:
            a, b = str(seg[0])[:8], str(seg[1])[:8]
            if a in points and b in points:
                segments.append([a, b])

    polygons: list[list[str]] = []
    for poly in draw.get("polygons") or []:
        if isinstance(poly, (list, tuple)) and len(poly) >= 3:
            names = [str(n)[:8] for n in poly]
            if all(n in points for n in names):
                polygons.append(names)

    circles: list[dict[str, Any]] = []
    for c in draw.get("circles") or []:
        if not isinstance(c, dict):
            continue
        center = str(c.get("center") or "")[:8]
        try:
            radius = float(c.get("radius", 1))
        except (TypeError, ValueError):
            continue
        if center in points and radius > 0:
            circles.append({"center": center, "radius": radius})

    # Default triangle if empty
    if not points:
        points = {"A": [-2, -1], "B": [2, -1], "C": [0, 2]}
        polygons = [["A", "B", "C"]]
        segments = [["A", "B"], ["B", "C"], ["C", "A"]]

    return {
        "kind": "geometry",
        "title": str(draw.get("title") or viz.get("title") or scene.get("title") or "Geometry")[:80],
        "notice": str(draw.get("notice") or scene.get("narration") or "Observe the geometric construction.")[:200],
        "points": points,
        "segments": segments[:12],
        "polygons": polygons[:4],
        "circles": circles[:4],
    }


def _sanitize_matrix_draw(
    draw: dict[str, Any],
    *,
    scene: dict[str, Any],
    viz: dict[str, Any],
) -> dict[str, Any]:
    matrix = draw.get("matrix") or draw.get("before") or viz.get("math_expression") or "[[1, 0], [0, 1]]"
    after = draw.get("after")
    return {
        "kind": "matrix",
        "title": str(draw.get("title") or viz.get("title") or scene.get("title") or "Matrix")[:80],
        "notice": str(draw.get("notice") or scene.get("narration") or "Compare the matrices.")[:200],
        "matrix": str(matrix)[:200],
        "after": str(after)[:200] if after else None,
    }


def _extract_rhs(expr: str) -> str:
    s = expr.strip()
    if "=" in s:
        return s.split("=", 1)[1].strip()
    return s


def normalize_math_expr(raw: str) -> str:
    """Normalize latex-ish math to SymPy-friendly ASCII."""
    s = raw.strip()
    s = s.replace("$$", "").replace("$", "")
    s = s.replace("\\left", "").replace("\\right", "")
    s = s.replace("\\,", "").replace("\\;", "").replace("\\!", "")
    s = s.replace("\\times", "*").replace("\\cdot", "*")
    s = s.replace("\\ ", " ")
    while True:
        m = re.search(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", s)
        if not m:
            break
        s = s[: m.start()] + f"({m.group(1)})/({m.group(2)})" + s[m.end() :]
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("^", "**")
    s = s.replace("\\", "")
    # Strip y= / f(x)= prefixes for function bodies
    s = re.sub(r"(?i)^\s*(y|f\s*\(\s*x\s*\))\s*=\s*", "", s)
    # Implicit multiplication: 2x -> 2*x, ax -> a*x when a is a single letter param
    s = re.sub(r"(\d)\s*([a-zA-Z(])", r"\1*\2", s)
    s = re.sub(r"([a-zA-Z)])\s*(\()", r"\1*\2", s)
    return s.strip()


def safe_parse_function(
    raw: str, extra_symbols: Optional[list[str]] = None
) -> Optional[dict[str, str]]:
    """Parse a function of x (and optional parameters) safely via SymPy.

    Returns {"expr": canonical_str} or None if unsafe/unparseable.
    """
    if not raw or not str(raw).strip():
        return None
    # Reject obvious code injection
    lowered = str(raw).lower()
    banned = ("import", "exec", "eval", "open(", "__", "os.", "sys.", "subprocess", "lambda")
    if any(b in lowered for b in banned):
        return None

    normalized = normalize_math_expr(str(raw))
    if not normalized or len(normalized) > 120:
        return None
    if not re.fullmatch(r"[0-9a-zA-Z_\s\+\-\*/\.\(\),]+", normalized):
        return None

    locals_map = dict(_SAFE_LOCALS)
    if extra_symbols:
        for name in extra_symbols:
            name = re.sub(r"[^a-zA-Z_]", "", name)[:8]
            if name and name not in locals_map:
                locals_map[name] = sp.symbols(name)

    try:
        # Avoid implicit_multiplication — it breaks already-explicit "x**2" when
        # combined with a restricted global_dict. Expressions are normalized above.
        expr = parse_expr(
            normalized,
            local_dict=locals_map,
            transformations=standard_transformations,
            evaluate=True,
        )
    except Exception:
        return None

    # Must involve only known symbols
    free = {str(s) for s in expr.free_symbols}
    allowed = set(locals_map.keys())
    if not free.issubset(allowed):
        return None

    try:
        canon = str(sp.simplify(expr))
        canon = canon.replace("^", "**")
    except Exception:
        return None
    if not re.fullmatch(r"[0-9a-zA-Z_\s\+\-\*/\.\(\),]+", canon):
        return None
    return {"expr": canon}


def safe_substitute_param(family_expr: str, param: str, value: float) -> Optional[str]:
    parsed = safe_parse_function(family_expr, extra_symbols=[param])
    if not parsed:
        return None
    try:
        locals_map = dict(_SAFE_LOCALS)
        param_clean = re.sub(r"[^a-zA-Z_]", "", param)[:8] or "a"
        if param_clean not in locals_map:
            locals_map[param_clean] = sp.symbols(param_clean)
        expr = parse_expr(
            parsed["expr"],
            local_dict=locals_map,
            transformations=standard_transformations,
            evaluate=True,
        )
        result = expr.subs(sp.symbols(param_clean), float(value))
        canon = str(sp.simplify(result)).replace("^", "**")
        if not re.fullmatch(r"[0-9a-zA-Z_\s\+\-\*/\.\(\),]+", canon):
            return None
        return canon
    except Exception:
        return None
