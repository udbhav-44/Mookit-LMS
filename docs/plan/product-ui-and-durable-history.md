# Plan — Full-Product Instructor UI ("/app") + Durable Chat History

> Status: **approved**. Source of truth for the next implementation phase. The standalone demo at
> `/ui` is a regression baseline and must not change.

## Context

The current `sample-ui/index.html` (served at `/ui`) is a capable **single-screen demo**, but it is not a product: it has no chat history (a reload loses everything), no way to revisit/continue past conversations, and no consolidated view of what's uploaded or drafted *in the current chat*. Backend exploration revealed the deeper reason: the `sessions`/`messages` tables exist but are **never written** (transcripts live only in Redis with a 24h TTL), there is **no list-sessions endpoint**, and uploads/drafts are scoped to `(tenant, user)` — **not to a session**. So the requested experience ("see previous chats, re-continue them, see what's uploaded in this chat, full access to every feature with easy navigation") cannot be delivered in the UI alone.

This plan builds a **new three-pane product UI** at `/app` (Preact + htm, **no build step**, vendored ES modules) that exposes every existing capability with first-class navigation, **plus the minimal backend additions** (durable sessions/messages, a list endpoint, per-session scoping of uploads/drafts) that make chat history and per-chat context real. The existing demo at `/ui` is left **completely untouched** and keeps working as a regression baseline. The quiz editing *depth* is deliberately scoped as a swappable slot — its UX is being decided in a separate follow-up discussion.

**Locked decisions** (from user): Preact+htm no-build · full durable history with an Alembic migration · polished "Connect" screen (course/uid/token) · three-pane workspace (left chat history · center chat · right "this chat" context).

## Goals / Non-goals

- **Goals:** product-grade navigation; list + re-open + continue past chats; per-chat uploads & drafts panel; expose all features (quiz/announcement/lecture drafting+editing+publish-with-confirm, file upload + diagram status, permissions/limits, source citations); no mock/demo-only flourishes; demo UI unaffected.
- **Non-goals (this plan):** redesigning quiz generation/editing internals (separate discussion — build the slot only); a real login/SSO (auth stays mooKIT header-based); multi-instance switching UI; mobile-first rewrite (responsive collapse only).

---

## Part 1 — Backend additions (durable history + per-session scoping)

All changes are **additive and backward-compatible**: new nullable columns, new endpoints, new optional kwargs. `Base.metadata.create_all` (startup path when `settings.auto_create_tables`) covers a fresh DB; the Alembic migration covers existing DBs (it must use explicit `op.add_column` because `0001_initial` uses `create_all`, which never alters existing tables).

### 1.1 Schema — `app/store/db.py`
- `Session`: add `title: str | None` (String(512)) and `updated_at: datetime` (default + `onupdate`, mirroring `Artifact.updated_at`). Add `__table_args__` index on `(tenant_key, user_id, updated_at)`.
- `FileMeta`: add `session_id: str | None` (String(36), indexed).
- `Artifact`: add `session_id: str | None` (String(36), indexed).

### 1.2 Migration — `migrations/versions/0002_session_history.py`
`down_revision = "0001_initial"`. Explicit `op.add_column` for the four columns + `op.create_index` for the three indexes; `downgrade()` drops them. Docstring notes the `create_all`/migration convergence.

### 1.3 Session/message repository — new `app/store/session_repo.py`
Keeps `chat.py` thin and testable; writes go through `app.state.session_factory`.
- `upsert_session(session_factory, ctx, *, first_user_message)` — idempotent `INSERT ... ON CONFLICT (id) DO UPDATE SET updated_at=now`; sets `title` from the first user message (trimmed ~80 chars, fallback "New chat") only when currently NULL.
- `persist_message(session_factory, ctx, role, content, meta=None)` — INSERT into `messages`.
- `list_sessions(session_factory, ctx, *, limit, offset, q=None)` — scoped by `tenant_key`+`user_id`, ordered `updated_at DESC`, with message/artifact counts.
- `list_session_messages(session_factory, ctx, session_id)` — Postgres transcript fallback.

### 1.4 Durable writes — `app/api/chat.py` `event_generator()`
Mirror the existing `_safe_audit` pattern with a `_safe_persist` wrapper so a missing/failing DB **never aborts the SSE stream** (keeps `tests/api/test_chat_sse.py` green). Hook points:
- Before streaming (after `chat_start` audit, ~`chat.py:75`): `upsert_session(...)` + `persist_message("user", body.message)`.
- During streaming: accumulate assistant text by parsing yielded `assistant_delta` events (the same dicts already produced by `_sse`).
- On `done`/`finally`: `persist_message("assistant", buffer)` if non-empty, then `upsert_session(...)` to bump `updated_at`.
- Dual-write is intentional: Redis stays authoritative for live context windows (orchestrator keeps writing it at `app/core/orchestrator.py:123/188`); Postgres is the durable record. **Document this so it isn't "optimized" away.** One concatenated assistant message per HTTP turn (flagged as a fidelity choice).

### 1.5 Session endpoints — `app/api/sessions.py` (prefix `/v1/sessions`)
- `GET /v1/sessions` (`@router.get("")`): list → `{sessions:[{id,title,updatedAt,createdAt,summary,messageCount,artifactCount}]}`; `?limit&offset&q` (q client-side-filterable in v1).
- Extend `GET /v1/sessions/{id}`: add Postgres fallback when the Redis transcript is cold (currently Redis-only at `sessions.py:43-49`); add `title`/`updatedAt` to the response (additive).
- `GET /v1/sessions/{id}/artifacts`: `{uploads:[…uploaded_file…], drafts:[…assessment/announcement/lecture_draft…]}` filtered by `session_id`; for uploads include `extraction_status` + diagram readiness so the right pane renders without re-polling.

### 1.6 Per-session scoping at creation
- `app/api/files.py` `upload_file()`: set `FileMeta.session_id = ctx.session_id` (and on the registered `uploaded_file` artifact).
- `app/store/durable_artifact_registry.py` `add()`: persist `session_id=ctx.session_id`; add an optional `session_id=None` filter kwarg to `list()` (default preserves current behavior). `ctx.session_id` already comes from the `x-session-id`/`session` header (`app/core/context.py:51-56`) — both UIs send it.

### 1.7 Mount + middleware — `app/main.py`
- After the `/ui` mount (~`main.py:272`), add a parallel `StaticFiles` mount of `product-ui/` at `/app` (guarded by `os.path.isdir`).
- Add `/app` to the service-key exempt tuple (`main.py:247`). `/v1/*` API auth is unchanged.

---

## Part 2 — Frontend: `product-ui/` (Preact + htm, no build, served at `/app`)

Ships as static files exactly like the demo — **no Node/Vite, no Dockerfile/CI changes**. Uses an **import map** + **vendored ESM** (pinned Preact/htm/signals copied into `product-ui/vendor/`, no runtime CDN).

### 2.1 Directory layout
```
product-ui/
  index.html              # import map + <script type=module src=app/main.js>
  vendor/                 # pinned ESM: preact, hooks, htm, (optional) signals
  app/   main.js · api.js · sse.js · store.js · router.js · markdown.js · util.js
  components/
    App.js Connect.js Sidebar.js ChatStream.js Message.js ContextPanel.js FileRow.js MetaBanner.js Toasts.js
    drafts/  QuizDraft.js  AnnouncementDraft.js  LectureDraft.js
    modals/  ConfirmDialog.js  SourceViewer.js  PromptModal.js
```

### 2.2 Reuse (port from the current `sample-ui/index.html` — proven logic, by function name)
SSE-over-fetch reader + frame parser (`parseSseFrames`, `handleSseFrame`); confirm gate (`showConfirm`/`resolveAction`); themed modal infra with focus-trap/Esc (`openModal`/`closeModal`/`promptModal`/`confirmModal`); quiz draft render + edit wiring (`renderQuizQuestion`/`renderDraftCard`/`setupQuizEditing`/`editQuiz`); upload + diagram status (`renderFileRow`/`pollFileStatus`/`uploadOneFile`/`loadDiagramThumbs`); permissions (`can`/`gate`); errors/toasts (`friendlyError`/`surfaceError`/`toast`); safe markdown (`renderMarkdown`); meta badges (`loadMeta`). These are lifted into `app/*.js` + components, not reinvented.

### 2.3 State model — `app/store.js`
`{ conn:{baseUrl,course,uid,token,connected,meta}, sessions:[…], sessionSearch, current:{ sessionId, messages:[…], streaming, abortController, toolChips, uploads:[…], drafts:[…], pendingConfirmation } }`. SSE → state mapping: `assistant_delta`→append; `tool_started/progress`→upsert tool chip + skeleton; `artifact_updated`→upsert `current.drafts` (right pane) **and** render inline draft card (center); `pending_confirmation`→open ConfirmDialog; `error`→toast; `done`→finalize, then refresh `GET /v1/sessions` (reorders sidebar) + `GET /v1/sessions/{id}/artifacts`.

### 2.4 Three panes + Connect
- **Connect.js** — course/uid/token (+ optional service URL); persists to the same `localStorage` key shape the demo uses (interop); `?token=` supported; validates via `GET /v1/meta`; stores `meta.permissions`; routes to `#/c/:sessionId`.
- **Sidebar.js** — "New chat" mints `sess-<rand>` + navigates; list from `GET /v1/sessions`; client-side search; active highlight; arrow/Enter keyboard nav.
- **ChatStream.js** — composer (Enter send / Shift+Enter newline), Cancel→abort, skeletons, empty-state example prompts, post-`done` quick-action chips, permission-gated Publish/Send buttons.
- **ContextPanel.js ("this chat")** — Uploads (FileRow with diagram badges/thumbs; remove→`DELETE /v1/files/{id}`) + Drafts (open=jump to inline card; type-specific actions). Seeded from `GET /v1/sessions/{id}/artifacts`, kept live by SSE + the upload poller.
- **Modals** — ConfirmDialog (full publish/send gate incl. announcement pre-send edit via `POST /v1/actions/{id}/revise` and per-action labels), SourceViewer (citation quote), PromptModal (themed prompt/confirm).

### 2.5 Previous-chats / re-continue (end to end)
Sidebar `GET /v1/sessions` → click → route `#/c/:id` → parallel `GET /v1/sessions/{id}` (transcript, Redis-hot or Postgres-cold) + `GET /v1/sessions/{id}/artifacts` (rebuild uploads/drafts + re-render inline cards) → user types → `POST /v1/chat {message, sessionId:id}` with `x-session-id:id` → same `session_id` flows into `ctx`, so the Redis focus stack, durable writes, and artifact scoping all continue on that session; `upsert_session` bumps `updated_at` (chat jumps to top).

### 2.6 Cross-cutting
Permission gating from `conn.meta.permissions`; toast + inline error surfacing; per-pane empty states; modal focus-trap/Esc/ARIA; responsive collapse of side panes into header-toggled drawers under ~900px (center chat always primary).

---

## Part 3 — Quiz workspace (placeholder slot; depth TBD separately)

`components/drafts/QuizDraft.js` renders the draft and wires the **already-existing** deterministic editor `POST /v1/quiz/{id}/edit` (ops: `edit_text|regenerate|replace_similar|change_type|flag|add|remove|set_difficulty`) plus Publish→confirm gate. Advanced controls (regenerate-with-note, change-type, rubric, bloom flags, difficulty knobs) sit behind a `FEATURES.quizDeepEdit` flag (default off) so v1 ships a clean draft view + basic Publish/Add/Make-harder, and the component can be swapped wholesale once the separate quiz-UX decision lands. (Announcement editing uses the existing `POST /v1/announcement/{id}/edit`; lecture draft uses week/module/release controls.)

---

## Coexistence & backward-compatibility guarantees
- `sample-ui/` is **not modified**; `/ui` keeps serving the demo unchanged (explicit regression check in verification).
- New columns are nullable; new endpoints are additive; modified endpoints only add response fields + a cold-read fallback; registry changes are optional kwargs.
- Durable writes wrapped in best-effort `_safe_persist` → SSE never blocked, existing fake-store tests unaffected.

## Risks (flagged)
1. Dual transcript write (Redis+Postgres) — intentional; capture assistant text from the same `assistant_delta` stream to avoid drift. 2. One concatenated assistant message per turn (history fidelity choice). 3. Confirm `conftest.py` app wiring before deciding `_safe_persist` is mandatory vs defensive. 4. Vendored ESM must be pinned (no CDN; CSP/offline safe). 5. Demo uploads now also get `session_id` — harmless (demo lists by file status, not session). 6. `GET /v1/sessions` ("") vs `/{session_id}` — exact route registers fine; verify no shadowing.

## Milestones
- **M1** Schema + migration + `session_repo` + chat.py dual-write + `GET /v1/sessions` & `{id}` fallback.
- **M2** Per-session scoping (files + artifacts) + `GET /v1/sessions/{id}/artifacts`.
- **M3** `product-ui/` shell + vendored ESM + `/app` mount + Connect screen.
- **M4** Three panes + SSE wiring + re-continue.
- **M5** Drafts + modals + quiz placeholder.
- **M6** Polish: toasts, empty states, a11y, mobile drawers.

## Verification (end to end)
Run dev (`auto_create_tables`) or `alembic upgrade head`; start uvicorn; open `http://<host>:8000/app`.
1. Connect (course/uid/token) → workspace; meta badges show permissions. 2. New chat → "Create a 5-question quiz on photosynthesis" → stream + draft card (center + right pane). 3. Upload a PDF → right-pane file row shows extraction + diagram status. 4. Edit a question / "Make harder" → `/v1/quiz/{id}/edit`. 5. Publish → confirm dialog → `/v1/actions/{id}/confirm`. 6. **Reload** → sidebar lists the chat (title + updatedAt); open it → transcript + drafts + uploads restore (durability). 7. Open `/ui` → demo still works (regression guard).
Tests to add: `tests/api/test_sessions.py` (upsert idempotency, title derivation, list ordering/isolation, Postgres fallback, `/artifacts` filtering); extend `tests/api/test_chat_sse.py` (Session+Message rows written); `FileMeta.session_id` populated; migration smoke (apply `0002` over `0001`). Keep full suite green + `ruff` clean + validate `product-ui` JS under V8 (parse-without-execute), matching the prior workflow.

## Critical files
- Backend (edit): `app/store/db.py`, `app/api/chat.py`, `app/api/sessions.py`, `app/api/files.py`, `app/store/durable_artifact_registry.py`, `app/main.py`.
- Backend (new): `migrations/versions/0002_session_history.py`, `app/store/session_repo.py`.
- Frontend (new): entire `product-ui/` tree.
- Reference-only (port from, do not edit): `sample-ui/index.html`.
