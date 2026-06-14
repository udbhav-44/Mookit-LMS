"""GPT-4o vision extractor — finds questions and diagram bboxes in PDF page images.

Uses the existing OpenAI config (settings.openai) rather than any additional
AI provider.  The model is called once per page with the rendered PNG; for pages
where a diagram bbox is missing on the first pass a second targeted call attempts
to locate it.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import List, Optional

from openai import AsyncOpenAI

from .models import BBox, DiagramInfo
from .pdf_renderer import RenderedPage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a precise document analyst. Your job is to find every quiz question on the
page and detect whether a rendered diagram/figure/chart/graph/image is visually
present on the page for that question.

CRITICAL: has_diagram is TRUE only when a rendered visual element already exists on
the page. It is FALSE when the question merely asks a student to draw something.

For each question return a JSON object with:
  - question_number: visible label like "Q1", "1.", "2", or null
  - question_text: the full question stem (no answer choices)
  - has_diagram: boolean
  - diagram_description: brief label e.g. "bar chart of annual sales" (null if none)
  - diagram_bbox: {x1, y1, x2, y2} tight around the diagram region only, coords
    normalized 0–1000 (null if no diagram)
  - question_bbox: {x1, y1, x2, y2} tight around question text (null if unsure)
  - choices: list of answer choice strings in reading order (empty list if none)
  - confidence: float 0–1

Return a JSON object: {"questions": [...]}
""".strip()

_LOCATE_PROMPT = """
Find the bounding box of a specific diagram on this page.
Return JSON: {"diagram_bbox": {"x1":..., "y1":..., "x2":..., "y2":...}} or
             {"diagram_bbox": null} if not found.
Coordinates normalized 0–1000.
""".strip()


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


class _PageQuestionRaw:
    """Temporary holder parsed from the raw model JSON for one question."""
    def __init__(self, data: dict) -> None:
        self.question_number: Optional[str] = data.get("question_number")
        self.question_text: str = str(data.get("question_text", ""))
        self.has_diagram: bool = bool(data.get("has_diagram", False))
        self.diagram_description: Optional[str] = data.get("diagram_description")
        self.choices: List[str] = data.get("choices") or []
        self.confidence: float = float(data.get("confidence", 0.5))
        # bbox
        raw_dbbox = data.get("diagram_bbox")
        self.diagram_bbox: Optional[BBox] = _parse_bbox(raw_dbbox)
        raw_qbbox = data.get("question_bbox")
        self.question_bbox: Optional[BBox] = _parse_bbox(raw_qbbox)


def _parse_bbox(raw: object) -> Optional[BBox]:
    if not isinstance(raw, dict):
        return None
    try:
        b = BBox(**{k: int(v) for k, v in raw.items() if k in ("x1", "y1", "x2", "y2")})
        return b
    except Exception:
        return None


class OpenAIDiagramExtractor:
    """Extracts questions and diagram bboxes from rendered PDF page images using GPT-4o."""

    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def extract_page(self, page: RenderedPage) -> List[_PageQuestionRaw]:
        """Return raw question records (with bbox info) for one page."""
        if not page.has_text and not page.has_graphics:
            return []

        diagram_hint = (
            "This page contains graphical content — a rendered diagram may be present."
            if page.has_graphics else
            "This page has NO vector drawings or images. has_diagram MUST be false for every "
            "question, even if the question asks the student to draw something."
        )

        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{_encode_image(page.api_image_path)}",
                    "detail": "high",
                },
            },
            {
                "type": "text",
                "text": (
                    f"Page {page.page_number}. {diagram_hint}\n\n"
                    f"Extracted text (reference only — image is authoritative):\n"
                    f"{page.text if page.text else '[no extractable text]'}\n\n"
                    "Return JSON {\"questions\": [...]} following the schema."
                ),
            },
        ]

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.error("OpenAI call failed for page %d: %s", page.page_number, exc)
            raise

        raw_text = resp.choices[0].message.content or "{}"
        try:
            payload = json.loads(raw_text)
            questions_raw = payload.get("questions", [])
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse JSON for page %d: %s", page.page_number, exc)
            return []

        parsed = []
        for q_data in questions_raw:
            try:
                parsed.append(_PageQuestionRaw(q_data))
            except Exception as exc:
                logger.warning("Skipping malformed question on page %d: %s", page.page_number, exc)

        # Second pass: for any question where has_diagram=True but bbox is still missing,
        # ask the model to locate it specifically.
        for q in parsed:
            if q.has_diagram and q.diagram_bbox is None and page.has_graphics:
                logger.info("Running locate pass for page %d: %.60s", page.page_number, q.question_text)
                q.diagram_bbox = await self._locate_diagram(page, q)

        return parsed

    async def _locate_diagram(self, page: RenderedPage, q: _PageQuestionRaw) -> Optional[BBox]:
        desc = q.diagram_description or "diagram or figure"
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _LOCATE_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{_encode_image(page.api_image_path)}",
                                    "detail": "high",
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    f'Question: "{q.question_text[:200]}"\n'
                                    f"Diagram described as: {desc}\n"
                                    "Return tight bbox around ONLY the diagram region."
                                ),
                            },
                        ],
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=256,
            )
            raw = json.loads(resp.choices[0].message.content or "{}")
            return _parse_bbox(raw.get("diagram_bbox"))
        except Exception as exc:
            logger.warning("Locate pass failed for page %d: %s", page.page_number, exc)
            return None
