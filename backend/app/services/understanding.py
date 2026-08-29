"""LLM-based mathematical understanding, lesson planning, scripting, and scene specs."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


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
Analyze AUTHORITATIVE textbook page content that has already been OCR'd and human-reviewed.

Rules:
- Distinguish CONTENT FOUND ON PAGE from AI EXPLANATION.
- Never invent equations, numbers, or definitions not present on the page.
- If something is ambiguous, mark it under "uncertainties" instead of guessing.
- Return structured JSON only."""

        user = f"""Analyze this reviewed textbook page content and return JSON:
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
(3–8 minutes) explaining a single textbook page. Return JSON only. Do not invent page content."""

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
- Use examples from the uploaded page only.
- Highlight common mistakes.
- Keep language clear for the learner's level.
- Structure into the standard 8 scenes when appropriate:
  1 title, 2 page overview, 3 concept, 4 worked example, 5 why explanation,
  6 additional visualization, 7 summary, 8 practice question.
- Do NOT hallucinate mathematics. If unsure, omit rather than invent.
Return JSON only."""

        user = f"""Generate narration script JSON:
{{
  "full_script": "concatenated narration",
  "segments": [
    {{
      "scene_id": "scene_01",
      "title": "Title",
      "scene_type": "title_card|textbook_page|concept|algebra_steps|why_explanation|summary_card|practice|graph_2d|geometry|number_line|matrix|custom",
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

Rules:
- Only request visualizations when they improve understanding (not every sentence).
- For algebra, include explicit step arrays that must be mathematically correct.
- visualization.type must be one of:
  title_card, textbook_page, algebra_steps, graph_2d, geometry, number_line,
  matrix, concept, why_explanation, summary_card, practice, none
- For textbook_page scenes, include highlight_bbox if available from page content.
Return JSON: {"scenes": [...]}"""

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
        "highlight_bbox": null,
        "title": "...",
        "bullets": [],
        "practice_question": null,
        "practice_answer": null
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
        return scenes
