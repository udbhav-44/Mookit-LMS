"""Diagram extraction pipeline.

Orchestrates:
  1. PDF → page PNGs (PyMuPDF, full-res + API-res copies)
  2. GPT-4o vision → questions + diagram bboxes per page
  3. Crop diagram regions from the full-res images (Pillow)
  4. Persist results in Redis under diagrams:{tenant_key}:{file_id}

The result is a DiagramExtractionResult that the quiz-generation tool can read to
attach cropped diagram images to the questions it creates in mooKIT.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import redis.asyncio as aioredis
from PIL import Image

from .extractor import OpenAIDiagramExtractor
from .models import BBox, DiagramExtractionResult, DiagramInfo
from .pdf_renderer import render_pdf_pages

logger = logging.getLogger(__name__)

_REDIS_TTL = 7 * 86400   # 1 week — same as RAG chunks


def _diagrams_key(tenant_key: str, file_id: str) -> str:
    return f"diagrams:{tenant_key}:{file_id}"


def _bbox_to_pixels(bbox: BBox, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(width,  round(bbox.x1 / 1000 * width)))
    y1 = max(0, min(height, round(bbox.y1 / 1000 * height)))
    x2 = max(0, min(width,  round(bbox.x2 / 1000 * width)))
    y2 = max(0, min(height, round(bbox.y2 / 1000 * height)))
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    return x1, y1, x2, y2


def _crop_diagram(page_image: Path, bbox: BBox, out_path: Path) -> None:
    with Image.open(page_image) as img:
        x1, y1, x2, y2 = _bbox_to_pixels(bbox, img.width, img.height)
        if x2 - x1 < 5 or y2 - y1 < 5:
            raise ValueError(f"Diagram bbox too small to crop: {bbox}")
        crop = img.crop((x1, y1, x2, y2))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_path)


async def run_diagram_pipeline(
    *,
    file_id: str,
    file_path: str,
    tenant_key: str,
    upload_dir: str,
    openai_api_key: str,
    openai_model: str,
    redis: aioredis.Redis,
    progress_cb: Callable[[int, str], None] | None = None,
) -> DiagramExtractionResult:
    """Run the full diagram extraction pipeline for one uploaded PDF.

    Writes results to Redis and returns the DiagramExtractionResult.
    Non-PDF files are silently skipped (status="skipped").
    """
    pdf_path = Path(file_path)

    if pdf_path.suffix.lower() != ".pdf":
        result = DiagramExtractionResult(file_id=file_id, status="skipped")
        await _save_result(redis, tenant_key, file_id, result)
        return result

    # Work directory: alongside the uploaded file, namespaced by file_id
    work_dir = Path(upload_dir) / tenant_key / f"{file_id}_diagrams"
    pages_dir = work_dir / "pages"
    diagrams_dir = work_dir / "diagrams"

    async def _progress(pct: int, msg: str) -> None:
        if progress_cb:
            await progress_cb(pct, msg)  # type: ignore[misc]

    try:
        await _progress(5, "Rendering PDF pages…")
        rendered_pages = render_pdf_pages(pdf_path, pages_dir, dpi=300)
        logger.info("Rendered %d pages for file_id=%s", len(rendered_pages), file_id)

        extractor = OpenAIDiagramExtractor(api_key=openai_api_key, model=openai_model)

        all_diagrams: list[DiagramInfo] = []
        total = len(rendered_pages)

        for i, page in enumerate(rendered_pages, start=1):
            pct = 5 + int(i / total * 85)
            await _progress(pct, f"Extracting diagrams from page {i}/{total}…")

            try:
                questions = await extractor.extract_page(page)
            except Exception as exc:
                logger.error("Extraction failed for page %d of %s: %s", page.page_number, file_id, exc)
                continue

            for q_idx, q in enumerate(questions):
                if not q.has_diagram or q.diagram_bbox is None:
                    continue

                # Try heuristic fallback: if diagram_bbox is missing but question_bbox
                # exists, crop everything below the question text to the bottom of page.
                bbox = q.diagram_bbox
                if bbox is None and q.question_bbox is not None:
                    qb = q.question_bbox
                    try:
                        bbox = BBox(
                            x1=max(0, qb.x1 - 20),
                            y1=min(999, qb.y2 + 5),
                            x2=min(1000, qb.x2 + 20),
                            y2=1000,
                        )
                    except Exception:
                        continue

                if bbox is None:
                    continue

                rel_name = f"page_{page.page_number:04d}_q{q_idx + 1:02d}.png"
                out_path = diagrams_dir / rel_name

                try:
                    _crop_diagram(page.image_path, bbox, out_path)
                except Exception as exc:
                    logger.warning("Failed to crop diagram on page %d q%d: %s", page.page_number, q_idx + 1, exc)
                    continue

                all_diagrams.append(DiagramInfo(
                    page_number=page.page_number,
                    question_index=q_idx,
                    question_number=q.question_number,
                    question_text=q.question_text,
                    diagram_description=q.diagram_description,
                    diagram_file=rel_name,
                    diagram_path=str(out_path),
                ))

        result = DiagramExtractionResult(
            file_id=file_id,
            diagrams=all_diagrams,
            total_pages=total,
            total_diagrams=len(all_diagrams),
            status="complete",
        )
        await _progress(100, f"Done — {len(all_diagrams)} diagram(s) extracted.")
        logger.info("Diagram pipeline complete: file_id=%s diagrams=%d", file_id, len(all_diagrams))

    except Exception as exc:
        logger.exception("Diagram pipeline failed for file_id=%s: %s", file_id, exc)
        result = DiagramExtractionResult(file_id=file_id, status="failed", error=str(exc))

    await _save_result(redis, tenant_key, file_id, result)
    return result


async def get_diagram_result(
    redis: aioredis.Redis, tenant_key: str, file_id: str
) -> DiagramExtractionResult | None:
    """Retrieve a previously stored DiagramExtractionResult from Redis."""
    raw = await redis.get(_diagrams_key(tenant_key, file_id))
    if not raw:
        return None
    return DiagramExtractionResult.model_validate_json(raw)


async def _save_result(
    redis: aioredis.Redis, tenant_key: str, file_id: str, result: DiagramExtractionResult
) -> None:
    key = _diagrams_key(tenant_key, file_id)
    await redis.set(key, result.model_dump_json(), ex=_REDIS_TTL)
