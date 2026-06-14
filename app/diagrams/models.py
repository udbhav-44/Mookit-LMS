"""Pydantic models for diagram extraction results.

These are stored in Redis under:
    diagrams:{tenant_key}:{file_id}
and surfaced through GET /v1/files/{file_id}/status so the quiz-generation
tool can attach diagram images (via fileIds) to the questions it creates.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class BBox(BaseModel):
    """Normalized bounding box — x1/y1 top-left, x2/y2 bottom-right, range 0–1000."""
    x1: int = Field(ge=0, le=1000)
    y1: int = Field(ge=0, le=1000)
    x2: int = Field(ge=0, le=1000)
    y2: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def _check_order(self) -> "BBox":
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("BBox requires x2 > x1 and y2 > y1")
        return self


class DiagramInfo(BaseModel):
    """One diagram linked to one question on a PDF page."""
    page_number: int
    question_index: int           # 0-based index within the page
    question_number: Optional[str] = None   # visible label e.g. "Q1"
    question_text: str
    diagram_description: Optional[str] = None
    # Relative path inside the per-file diagrams directory on disk
    diagram_file: str
    # Absolute server-side path — used to upload the cropped PNG to mooKIT /files/add
    diagram_path: str


class DiagramExtractionResult(BaseModel):
    """Stored in Redis after a successful diagram extraction pass on a file."""
    file_id: str
    diagrams: List[DiagramInfo] = Field(default_factory=list)
    total_pages: int = 0
    total_diagrams: int = 0
    status: str = "complete"   # complete | failed | skipped
    error: Optional[str] = None
