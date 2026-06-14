"""Render PDF pages to PNG images via PyMuPDF.

Produces two copies of each page:
  - full-res (300 DPI) — used for cropping diagram regions with pixel accuracy
  - api-res (capped at 1600 px long edge) — sent to the vision model to cut costs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pymupdf
from PIL import Image

logger = logging.getLogger(__name__)

_API_IMAGE_MAX_EDGE = 1600


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    image_path: Path        # full-res, used for cropping
    api_image_path: Path    # downscaled, sent to vision model
    text: str
    width: int
    height: int
    has_graphics: bool      # page has vector drawings or raster images
    has_text: bool


def _page_has_graphics(page: pymupdf.Page) -> bool:
    try:
        if page.get_images(full=True):
            return True
    except Exception:
        pass
    try:
        if page.get_drawings():
            return True
    except Exception:
        pass
    return False


def _write_api_image(full_path: Path, api_path: Path) -> None:
    with Image.open(full_path) as img:
        long_edge = max(img.width, img.height)
        if long_edge <= _API_IMAGE_MAX_EDGE:
            img.save(api_path)
            return
        scale = _API_IMAGE_MAX_EDGE / long_edge
        new_size = (round(img.width * scale), round(img.height * scale))
        img.resize(new_size, Image.LANCZOS).save(api_path)


def render_pdf_pages(pdf_path: Path, pages_dir: Path, dpi: int = 300) -> List[RenderedPage]:
    """Render every page of `pdf_path` into `pages_dir` and return metadata."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    api_dir = pages_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_path))
    logger.info("Rendering %d pages from %s", doc.page_count, pdf_path.name)
    rendered: List[RenderedPage] = []

    for idx in range(doc.page_count):
        page_num = idx + 1
        page = doc.load_page(idx)
        pix = page.get_pixmap(dpi=dpi, alpha=False)

        image_path = pages_dir / f"page_{page_num:04d}.png"
        pix.save(str(image_path))

        api_image_path = api_dir / f"page_{page_num:04d}.png"
        _write_api_image(image_path, api_image_path)

        text = (page.get_text("text") or "").strip()
        has_gfx = _page_has_graphics(page)

        rendered.append(RenderedPage(
            page_number=page_num,
            image_path=image_path,
            api_image_path=api_image_path,
            text=text,
            width=pix.width,
            height=pix.height,
            has_graphics=has_gfx,
            has_text=bool(text),
        ))
        logger.debug("Page %d: %dx%d px, graphics=%s, text_len=%d", page_num, pix.width, pix.height, has_gfx, len(text))

    return rendered
