# 04 — Functional Modules & Product UX

**Product north star:** *"We make suggestions. You make decisions."* Generate → review → edit → approve;
never auto-execute. Confirmation checkpoints scale with stakes. Output lands in real mooKIT objects.

## Module 1 — Assessment / Quiz generation
**Flow:** upload document → "Create a quiz from this PDF" → grounded draft → editable preview →
"Add to course" → published in mooKIT.

**UX:**
- Full **editable preview**, per question: edit · regenerate · **replace-with-similar** · change type ·
  change difficulty · **view source span** · delete.
- Adjustable **knobs:** Bloom level, difficulty (multi-tier), reading level, count, question-type mix.
- **Provenance badge** ("AI-generated · edited by you") + a **flag/feedback** control on every item.
- **Warnings** surfaced for higher-order Bloom or verification-flagged questions → nudge human review.
- No hard gate on individual edits; the publish step is gated.

**mooKIT mapping:** `POST /assessments/{type}` (status=0) → optional sections → `add_question` per item →
publish via `PUT ...published.status=1`. Question types: `mcq_single`, `mcq_multi`, `true_false`, `fib`,
`descriptive`. Bulk creation runs as an ARQ job with progress.

## Module 2 — Announcement assistant
**Flow:** "Inform students assignment deadline is extended" → AI drafts → preview with explicit audience &
channel → **Send / Schedule / Discard** → published/emailed.

**UX:**
- Preview shows the **audience chip** ("To: 142 students in CS101") and the **channel** (email vs LMS post).
- Required confirm dialog; **never sends on generation**.
- **Recipients resolved server-side** from the session — the model/document can never name a recipient.
- Body markdown sanitized (no model-generated outbound links/images).

**mooKIT mapping:** `POST /announcements/add` with `title`(subject), `description`(body),
`type`(normal/urgent), `notifyMail`(email vs LMS-only), `sectionIds`(audience; empty = all),
`published.{status:1, releaseOn}`. (Schedule = future `releaseOn`.)

## Module 3 — Lecture publishing assistant
**Flow:** upload video → "Publish this under Week 4 on Monday" → AI resolves course/week + generates title
→ change-summary preview → confirm → scheduled/published.

**UX:**
- Show a **diff/change-summary** (title, module/week, visibility, attachments, schedule) before confirm.
- Generated **lecture title** (+ optional description), editable.
- Required confirm; provenance recorded ("published by [instructor] via AI assistant").

**mooKIT mapping:** resolve "Week 4"/"Module 2" via `GET /taxonomies/{type}` → `weekId`/`topicId`;
`POST /files/add` (video) → `POST /lectures` → attach via `POST /lectures/{id}/course-resources`
(`resourceType:"video"`, `resourceFileId`, `isPrimary:true`) → schedule via `releaseOn`/`published`.
(Confirm intended video path — uploaded file vs Vimeo id vs URL — with the mooKIT team.)

## Confirmation tiers (risk-based, fights approval fatigue)
| Tier | Examples | Gate |
|---|---|---|
| read | list courses, fetch sections, view permissions | none (auto) |
| draft | generate quiz, draft announcement, edit a draft | none (auto) |
| **publish** | **publish assessment, send announcement, publish lecture** | **explicit confirm dialog** (token-bound, faithful preview) |

## Cross-module UX patterns (stolen from the best products)
- **Task-specific tools, not one open chatbot** (Khanmigo, Copilot Teach).
- **Grounded + cited** generation with "view source" (Cogniti onboarding-package model; Canvas IgniteAI "draft/foundation" framing).
- **Inline editability + conversational refine loop** ("replace with similar", "simplify", "change type/tone" — Khanmigo Coeditor, Wayground).
- **Provenance / edit-tracking** ("AI-generated · edited by instructor" — Anthology tracks whether AI output was edited).
- **Oversight + feedback** — a flag/feedback control on every AI output (Cogniti).
- **Differentiation knobs** — reading-level, length, difficulty, translation (Copilot, Google, Wayground).
- **Land in the real workflow** — commit directly into mooKIT objects, not a chat transcript to copy-paste from.
