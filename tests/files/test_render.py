"""PDF page rendering for vision comprehension (offline — builds a tiny PDF in-process)."""

import io

import pytest

from app.files.render import render_pdf_to_images


def _blank_pdf(n_pages: int = 1, size: tuple[int, int] = (200, 200)) -> bytes:
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        pdf.new_page(*size)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_renders_one_png_per_page() -> None:
    images = render_pdf_to_images(_blank_pdf(n_pages=3))
    assert len(images) == 3
    assert all(img[:8] == b"\x89PNG\r\n\x1a\n" for img in images)  # PNG magic bytes


def test_respects_max_pages() -> None:
    images = render_pdf_to_images(_blank_pdf(n_pages=5), max_pages=2)
    assert len(images) == 2


def test_rejects_non_pdf_bytes() -> None:
    with pytest.raises(ValueError):
        render_pdf_to_images(b"this is not a pdf")
