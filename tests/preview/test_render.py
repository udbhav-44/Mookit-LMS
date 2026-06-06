"""B3.4 acceptance — sanitizer + preview fidelity."""

from app.preview.render import (
    build_announcement_preview,
    build_lecture_preview,
    sanitize_markdown,
)


def test_sanitize_strips_links_and_images() -> None:
    md = "See ![pic](http://evil/x.png) and [click](http://evil) now at http://evil/raw"
    out = sanitize_markdown(md)
    assert "http" not in out
    assert "click" in out  # link text preserved
    assert "![" not in out


def test_sanitize_none() -> None:
    assert sanitize_markdown(None) == ""


def test_announcement_preview_audience_and_channel() -> None:
    p = build_announcement_preview(
        subject="Exam moved",
        body_markdown="The exam is moved. [link](http://x)",
        channel="email",
        audience_label="all students",
        urgent=True,
    )
    assert p.audience == "all students"
    assert "Email" in p.summary_lines[0]
    assert "Urgent" in p.summary_lines[1]
    assert "http" not in (p.body_markdown or "")


def test_lecture_preview_diff() -> None:
    p = build_lecture_preview(
        title="Intro",
        week_label="Week 4",
        module_label="Module 2",
        visibility="scheduled",
        schedule_label="2026-01-01 09:00 UTC",
        attachments=["art_5"],
    )
    fields = {d["field"] for d in (p.diff or [])}
    assert {"title", "week", "module", "visibility", "schedule", "attachments"} <= fields
