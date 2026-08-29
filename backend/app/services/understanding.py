"""LLM-based mathematical understanding, lesson planning, scripting, and scene specs."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Shared palette — gold, blue, green, rose, violet (also used by MathViz drawers)
CONCEPT_PALETTE = ["#F5C542", "#3B82F6", "#22C55E", "#F43F5E", "#A855F7"]

DRAW_SCENE_TYPES = frozenset(
    {
        "concept",
        "why_explanation",
        "algebra_steps",
        "graph_2d",
        "geometry",
        "number_line",
        "matrix",
        "custom",
        "textbook_page",  # remapped; still needs a draw if leftover
    }
)

CARD_ONLY_TYPES = frozenset({"title_card", "summary_card", "practice", "none"})


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
Prefer visualization types that DRAW the math (graph_2d, geometry, number_line, algebra_steps)
rather than showing a scanned page image."""

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
        system = f"""You convert a mathematics video script into structured scene specifications
for a MathVizAI-style Manim visualization engine.

Rules:
- NEVER request a scanned textbook page image. Do not use type textbook_page.
- Always ILLUSTRATE explanations: for concept, why_explanation, algebra_steps, graph_2d,
  geometry, number_line, matrix — include a visualization.draw block that can be drawn with
  Manim primitives (axes, curves, points, polygons, number lines). Title/summary/practice
  may be text cards without draw.
- Prefer graph_2d for functions/equations, geometry for shapes/angles, number_line for
  inequalities or roots on a line.
- Each series/point/region MUST have its own color from this palette (reuse the same color
  for the same concept if it reappears): {json.dumps(CONCEPT_PALETTE)}.
- Include a short legend (label + color) when there are 2+ visual series.
- For algebra, include explicit step arrays that must be mathematically correct.
- visualization.type must be one of:
  title_card, algebra_steps, graph_2d, geometry, number_line,
  matrix, concept, why_explanation, summary_card, practice, none
Return JSON: {{"scenes": [...]}}"""

        user = f"""Produce scene specs JSON:
{{
  "scenes": [
    {{
      "scene_id": "scene_01",
      "order_index": 0,
      "title": "...",
      "duration": 25,
      "narration": "...",
      "scene_type": "algebra_steps",
      "visualization": {{
        "type": "algebra_steps",
        "math_expression": "x^2 - 5x + 6 = 0",
        "steps": ["(x-2)(x-3)=0", "x=2 or x=3"],
        "title": "...",
        "bullets": [],
        "practice_question": null,
        "practice_answer": null,
        "draw": {{
          "kind": "graph_2d",
          "x_range": [-1, 6],
          "y_range": [-2, 8],
          "series": [
            {{"id": "curve", "label": "y = x^2 - 5x + 6", "expr": "x**2 - 5*x + 6", "color": "#F5C542"}},
            {{"id": "root_a", "label": "x = 2", "kind": "point", "x": 2, "y": 0, "color": "#3B82F6"}},
            {{"id": "root_b", "label": "x = 3", "kind": "point", "x": 3, "y": 0, "color": "#22C55E"}}
          ]
        }}
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
        return sanitize_scenes(scenes)


def sanitize_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remap textbook_page, strip highlight_bbox, ensure draw blocks for explanation scenes."""
    out: list[dict[str, Any]] = []
    for s in scenes:
        scene = dict(s)
        viz = dict(scene.get("visualization") or {})
        stype = (scene.get("scene_type") or viz.get("type") or "custom").lower()
        vtype = (viz.get("type") or stype).lower()

        # Never show scanned page
        if stype in ("textbook_page", "overview", "page_overview") or vtype in (
            "textbook_page",
            "overview",
            "page_overview",
        ):
            if _looks_like_function(viz.get("math_expression") or scene.get("title") or ""):
                stype = "graph_2d"
                vtype = "graph_2d"
            else:
                stype = "concept"
                vtype = "concept"
            scene["scene_type"] = stype
            viz["type"] = vtype

        viz.pop("highlight_bbox", None)

        needs_draw = vtype in DRAW_SCENE_TYPES and vtype not in CARD_ONLY_TYPES
        draw = viz.get("draw")
        if needs_draw and not isinstance(draw, dict):
            draw = _synthesize_draw(viz, scene)
            if draw:
                viz["draw"] = draw
        elif isinstance(draw, dict):
            viz["draw"] = _normalize_draw_colors(draw)

        # Align scene_type with draw kind when helpful
        if isinstance(viz.get("draw"), dict) and vtype in ("concept", "why_explanation", "custom"):
            kind = (viz["draw"].get("kind") or "").lower()
            if kind in ("graph_2d", "geometry", "number_line"):
                viz["type"] = kind
                if stype in ("concept", "why_explanation", "custom", "textbook_page"):
                    # Keep why_explanation as scene_type for narration semantics; type drives viz
                    if stype != "why_explanation":
                        scene["scene_type"] = kind

        viz["type"] = viz.get("type") or stype
        scene["scene_type"] = scene.get("scene_type") or viz["type"]
        scene["visualization"] = viz
        out.append(scene)
    return out


def _normalize_draw_colors(draw: dict[str, Any]) -> dict[str, Any]:
    d = dict(draw)
    series = list(d.get("series") or [])
    normalized = []
    for i, item in enumerate(series):
        entry = dict(item) if isinstance(item, dict) else {"label": str(item)}
        if not entry.get("color"):
            entry["color"] = CONCEPT_PALETTE[i % len(CONCEPT_PALETTE)]
        if not entry.get("id"):
            entry["id"] = f"s{i}"
        normalized.append(entry)
    d["series"] = normalized
    return d


def _synthesize_draw(viz: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any] | None:
    """Build a minimal colored draw block when the planner omitted one."""
    expr = (viz.get("math_expression") or "").strip()
    vtype = (viz.get("type") or scene.get("scene_type") or "").lower()
    title = scene.get("title") or viz.get("title") or "Concept"

    if vtype == "number_line" or (expr and _looks_like_inequality(expr)):
        points = _extract_numbers(expr)
        series = []
        for i, x in enumerate(points[:5]):
            series.append(
                {
                    "id": f"p{i}",
                    "label": f"x = {x}",
                    "kind": "point",
                    "x": x,
                    "color": CONCEPT_PALETTE[i % len(CONCEPT_PALETTE)],
                }
            )
        if not series:
            series = [
                {
                    "id": "mark",
                    "label": title[:40],
                    "kind": "point",
                    "x": 0,
                    "color": CONCEPT_PALETTE[0],
                }
            ]
        xs = [float(s["x"]) for s in series]
        pad = 2
        return {
            "kind": "number_line",
            "x_range": [min(xs) - pad, max(xs) + pad],
            "series": series,
        }

    if vtype == "geometry":
        return {
            "kind": "geometry",
            "shapes": [
                {
                    "id": "tri",
                    "kind": "polygon",
                    "points": [[-2, -1.5], [2, -1.5], [0, 2]],
                    "label": title[:30],
                    "color": CONCEPT_PALETTE[0],
                }
            ],
            "series": [
                {"id": "tri", "label": title[:30], "color": CONCEPT_PALETTE[0]},
            ],
        }

    # Default: graph if expression looks plottable, else simple concept axes + label
    py_expr = _latexish_to_python(expr) if expr else None
    if py_expr and _looks_like_function(expr):
        series: list[dict[str, Any]] = [
            {
                "id": "curve",
                "label": f"y = {expr}" if "=" not in expr else expr,
                "expr": py_expr,
                "color": CONCEPT_PALETTE[0],
            }
        ]
        # Hint roots from steps if present
        for i, step in enumerate(viz.get("steps") or []):
            for x in _extract_roots_from_text(str(step)):
                series.append(
                    {
                        "id": f"root_{i}_{x}",
                        "label": f"x = {x}",
                        "kind": "point",
                        "x": x,
                        "y": 0,
                        "color": CONCEPT_PALETTE[(len(series)) % len(CONCEPT_PALETTE)],
                    }
                )
        return {
            "kind": "graph_2d",
            "x_range": [-2, 6],
            "y_range": [-4, 8],
            "series": series,
        }

    # Concept card with a tiny illustrative number-line mark so something is drawn
    if vtype in ("concept", "why_explanation", "algebra_steps", "matrix", "custom", "textbook_page"):
        if py_expr:
            return {
                "kind": "graph_2d",
                "x_range": [-2, 6],
                "y_range": [-4, 8],
                "series": [
                    {
                        "id": "curve",
                        "label": expr or title[:40],
                        "expr": py_expr,
                        "color": CONCEPT_PALETTE[0],
                    }
                ],
            }
        return {
            "kind": "number_line",
            "x_range": [-5, 5],
            "series": [
                {
                    "id": "focus",
                    "label": (expr or title)[:40],
                    "kind": "point",
                    "x": 0,
                    "color": CONCEPT_PALETTE[0],
                }
            ],
        }
    return None


def _looks_like_function(text: str) -> bool:
    t = text.lower()
    return bool(
        re.search(r"[xX]\s*\^|x\*\*|sin|cos|tan|log|sqrt|x\s*[+\-*/]|=\s*0", t)
        or ("x" in t and any(c.isdigit() for c in t))
    )


def _looks_like_inequality(text: str) -> bool:
    return bool(re.search(r"[<>≤≥]|\\le|\\ge|\\leq|\\geq", text))


def _extract_numbers(text: str) -> list[float]:
    nums = re.findall(r"(?<![a-zA-Z])(-?\d+(?:\.\d+)?)", text)
    out: list[float] = []
    for n in nums:
        try:
            out.append(float(n))
        except ValueError:
            continue
    return out


def _extract_roots_from_text(text: str) -> list[float]:
    roots: list[float] = []
    for m in re.finditer(r"x\s*=\s*(-?\d+(?:\.\d+)?)", text, re.I):
        try:
            roots.append(float(m.group(1)))
        except ValueError:
            continue
    return roots


def _latexish_to_python(expr: str) -> str | None:
    """Best-effort convert simple textbook math to a Python expression in x."""
    s = expr.strip()
    s = re.sub(r"\$+", "", s)
    # Take LHS of equation if y = ... or ... = 0
    if "=" in s:
        left, right = s.split("=", 1)
        left, right = left.strip(), right.strip()
        if re.fullmatch(r"[yYfF]\(?x\)?", left) or left.lower() in ("y", "f(x)"):
            s = right
        elif right in ("0", "0.0"):
            s = left
        else:
            # difference form for plotting
            s = f"({left})-({right})"
    s = s.replace("^", "**")
    s = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"((\1)/(\2))", s)
    s = s.replace("\\", "")
    s = re.sub(r"(\d)\s*([a-zA-Z(])", r"\1*\2", s)
    s = re.sub(r"([a-zA-Z)])\s*(\d)", r"\1*\2", s)
    s = re.sub(r"\)\s*\(", ")*(", s)
    # Only keep if it looks like a safe expression
    if not re.fullmatch(r"[0-9xX+\-*/().\s*]+", s.replace("**", "")):
        # allow common names
        if not re.search(r"^[0-9xX+\-*/().\s*sincoatglqr]+$", s, re.I):
            return None
    s = s.replace("X", "x")
    try:
        compile(s, "<expr>", "eval")
    except SyntaxError:
        return None
    return s
