"""Mathematical OCR via OpenAI vision with structured LaTeX output."""

from __future__ import annotations

import base64
import json
from typing import Any

from openai import OpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.image_processing import preprocess_for_ocr

logger = get_logger(__name__)

OCR_SYSTEM_PROMPT = """You are a mathematical OCR specialist optimized for scanned mathematics textbooks.

Your job is to extract ALL content from the page with extreme accuracy for mathematical notation.

CRITICAL RULES:
1. Preserve mathematical notation EXACTLY. Convert every equation/expression to valid LaTeX.
2. NEVER confuse: x² with x2, √ with V, 0 with O, 1 with l, × with x, − with -.
3. Fractions must use \\frac{a}{b}. Roots use \\sqrt{}. Powers use ^.
4. Matrices, integrals, sums must use proper LaTeX environments.
5. Assign a confidence score 0.0–1.0 for each element. If unsure about a symbol, LOWER confidence and set needs_review=true. Do NOT guess.
6. Distinguish CONTENT FOUND ON THE PAGE from anything you might infer — only extract what is visible.
7. Bounding boxes are normalized [0,1] relative to image width/height: {x, y, width, height}.

Return ONLY valid JSON matching the schema."""

OCR_SCHEMA_INSTRUCTION = """
Return JSON with this shape:
{
  "full_text": "plain-text reading of the page with LaTeX inline where useful",
  "topic_guess": "short topic title if visible",
  "elements": [
    {
      "element_type": "heading|paragraph|equation|example|question|solution|definition|note|table|diagram|variable|other",
      "original_text": "as seen on page",
      "latex": "LaTeX if mathematical, else null",
      "bbox": {"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.05},
      "page_location": "top|middle|bottom|left|right|full",
      "confidence": 0.95,
      "needs_review": false
    }
  ]
}
"""


class OCRService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_vision_model
        self.threshold = settings.ocr_confidence_threshold

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        if not self.settings.openai_api_key or self.settings.openai_api_key.startswith(
            "sk-your-"
        ):
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. Set a real key in .env and restart api/worker."
            )

        processed = preprocess_for_ocr(image_bytes)
        b64 = base64.b64encode(processed).decode("ascii")

        logger.info("Running mathematical OCR with model %s", self.model)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": OCR_SYSTEM_PROMPT + OCR_SCHEMA_INSTRUCTION},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all mathematical content from this scanned textbook page. "
                                "Be especially careful with superscripts, roots, and equation symbols."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        )

        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("OCR returned invalid JSON: %s", content[:500])
            raise ValueError("OCR model returned invalid JSON") from exc

        elements = data.get("elements") or []
        for el in elements:
            conf = float(el.get("confidence", 0.5))
            el["confidence"] = conf
            if conf < self.threshold:
                el["needs_review"] = True
            # Flag equations without latex
            if el.get("element_type") == "equation" and not el.get("latex"):
                el["needs_review"] = True
                el["confidence"] = min(conf, 0.4)

        data["elements"] = elements
        data["full_text"] = data.get("full_text") or ""
        data["topic_guess"] = data.get("topic_guess") or ""
        data["model"] = self.model
        return data
