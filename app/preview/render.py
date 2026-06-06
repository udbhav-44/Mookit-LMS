"""B3.4 — faithful PreviewRender builders for all three modules.

Previews show the ACTUAL payload that will be sent (not a paraphrase). Markdown bodies are sanitized:
no model-generated outbound links / images (anti-exfil). The fields rendered must equal the
corresponding ProposedAction.payload fields (no drift) — asserted by tests.
"""

from __future__ import annotations

import re
from typing import Any

from app.contracts.types import PreviewRender

# Strip markdown links [text](url) -> text and images ![alt](url) -> "" (anti-exfil).
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RAW_URL = re.compile(r"https?://\S+")


def sanitize_markdown(text: str | None) -> str:
    if not text:
        return ""
    out = _MD_IMAGE.sub("", text)
    out = _MD_LINK.sub(r"\1", out)
    out = _RAW_URL.sub("[link removed]", out)
    return out.strip()


# --- Assessment ----------------------------------------------------------
def build_assessment_preview(*, title: str, questions: list[dict[str, Any]]) -> PreviewRender:
    summary = [f"{len(questions)} question(s)"]
    by_type: dict[str, int] = {}
    for q in questions:
        by_type[q["questionType"]] = by_type.get(q["questionType"], 0) + 1
    summary += [f"{n} × {t}" for t, n in sorted(by_type.items())]

    warnings: list[str] = []
    for i, q in enumerate(questions):
        if q.get("bloom_level") in {"analyze", "evaluate", "create"}:
            warnings.append(f"Q{i + 1} is higher-order Bloom ({q['bloom_level']}) — review carefully")
        if q.get("flags"):
            warnings.append(f"Q{i + 1} flagged: {', '.join(q['flags'])}")

    return PreviewRender(
        title=f"Publish assessment: {title}",
        summary_lines=summary,
        warnings=warnings,
    )


# --- Announcement --------------------------------------------------------
def build_announcement_preview(
    *,
    subject: str,
    body_markdown: str,
    channel: str,  # "email" | "lms"
    audience_label: str,  # intent label, e.g. "all students" / "Section 3"
    urgent: bool,
) -> PreviewRender:
    return PreviewRender(
        title=f"Send announcement: {subject}",
        summary_lines=[
            f"Channel: {'Email + LMS' if channel == 'email' else 'LMS only'}",
            f"Priority: {'Urgent' if urgent else 'Normal'}",
        ],
        audience=audience_label,
        body_markdown=sanitize_markdown(body_markdown),
    )


# --- Lecture -------------------------------------------------------------
def build_lecture_preview(
    *,
    title: str,
    week_label: str,
    module_label: str | None,
    visibility: str,  # "published" | "scheduled" | "draft"
    schedule_label: str | None,
    attachments: list[str],
    description_markdown: str | None = None,
) -> PreviewRender:
    diff = [
        {"field": "title", "before": None, "after": title},
        {"field": "week", "before": None, "after": week_label},
    ]
    if module_label:
        diff.append({"field": "module", "before": None, "after": module_label})
    diff.append({"field": "visibility", "before": None, "after": visibility})
    if schedule_label:
        diff.append({"field": "schedule", "before": None, "after": schedule_label})
    if attachments:
        diff.append({"field": "attachments", "before": None, "after": ", ".join(attachments)})

    return PreviewRender(
        title=f"Publish lecture: {title}",
        summary_lines=[f"{week_label}" + (f" · {module_label}" if module_label else ""), visibility],
        body_markdown=sanitize_markdown(description_markdown) if description_markdown else None,
        diff=diff,
    )
