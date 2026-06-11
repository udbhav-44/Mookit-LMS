"""PDF → page-image rendering for vision comprehension.

Engineering PDFs carry equations, diagrams, and tables that plain-text extraction (pdfminer) drops or
mangles. To let a multimodal model *read the page*, we render each PDF page to a PNG with pypdfium2
(permissively licensed, no system dependencies) and encode it via Pillow.

Pure and import-light: the heavy imports happen inside the function so importing this module never
requires the rendering stack to be installed unless a render is actually performed.
"""

from __future__ import annotations

import io

# Cap the number of pages we render per document — vision input is expensive and most quizzes only
# need a representative slice. Surfaced to the caller (which should log when pages are dropped).
DEFAULT_MAX_PAGES = 20
DEFAULT_SCALE = 2.0  # ~144 DPI; legible equations without oversized payloads


def render_pdf_to_images(
    data: bytes, *, max_pages: int = DEFAULT_MAX_PAGES, scale: float = DEFAULT_SCALE
) -> list[bytes]:
    """Render up to ``max_pages`` pages of a PDF (given as bytes) to PNG image bytes.

    Returns one PNG per rendered page, in document order. Raises ``ImportError`` if the rendering
    stack is unavailable, and ``ValueError`` if the bytes aren't a parseable PDF.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError("pypdfium2 is required for PDF page rendering") from exc

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 — surface a clean error for unparseable input
        raise ValueError(f"could not open PDF for rendering: {exc}") from exc

    images: list[bytes] = []
    try:
        n = min(len(pdf), max_pages)
        for i in range(n):
            bitmap = pdf[i].render(scale=scale)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            images.append(buf.getvalue())
    finally:
        pdf.close()
    return images
