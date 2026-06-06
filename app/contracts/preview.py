from pydantic import BaseModel, Field


class PreviewRender(BaseModel):
    title: str                         # "Publish quiz: Chapter 3 Quiz"
    summary_lines: list[str] = Field(default_factory=list)  # bullet summary of the change
    audience: str | None = None        # e.g. "142 students in CS101"  (announcements/lectures)
    body_markdown: str | None = None   # rendered announcement / lecture description (sanitized)
    diff: list[dict] | None = None     # [{field, before, after}] for updates
    warnings: list[str] = Field(default_factory=list)  # e.g. "5 higher-order Bloom — review"
