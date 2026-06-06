from pydantic import BaseModel

class PreviewRender(BaseModel):
    title: str                         # "Publish quiz: Chapter 3 Quiz"
    summary_lines: list[str]           # bullet summary of the change
    audience: str | None = None        # e.g. "142 students in CS101"  (announcements/lectures)
    body_markdown: str | None = None   # rendered announcement / lecture description (sanitized)
    diff: list[dict] | None = None     # [{field, before, after}] for updates
    warnings: list[str] = []           # e.g. "5 questions are higher-order Bloom — review carefully"
