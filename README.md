# mooKIT AI Assistant for Instructors

A standalone, multi-tenant microservice that lets instructors drive mooKIT through natural language:
**generate grounded quizzes from documents, draft/send announcements, and publish lectures** — always
with a deterministic human confirm before anything publishes or sends.

> *"We make suggestions. You make decisions."*

This repository is the **integrated product** of two tracks that meet at shared contracts
(`app/contracts/`):

- **Dev A — Platform / Integration / Security** (`app/main.py`, `app/api/*`, `app/mookit/*`,
  `app/store/*`, `app/core/{context,confirmation,executor,rate_limit}.py`, `app/files/*`,
  `app/workers/*`, `deploy/*`): FastAPI app, SSE, multi-tenancy, the typed `MooKitClient`,
  Redis/Postgres stores, sandboxed file ingestion + RAG, the confirmation gate + deterministic executor,
  audit, observability, rate-limiting, and deployment.
- **Dev B — AI Brain & Domain Logic** (`app/core/{orchestrator,memory,reference_resolver,prompts,
  guardrails}.py`, `app/llm/*`, `app/tools/*`, `app/gen/*`, `app/preview/*`, `app/evals/*`): the
  Plan-then-Execute orchestrator, two-channel memory, the RAG-grounded quiz pipeline, domain tools,
  `ProposedAction`/`PreviewRender`, prompt/safety design, and the eval harness.

The AI brain is wired in `app/core/wiring.py` (`app.state.orchestrator`). `POST /v1/chat` streams
events over SSE. Publish-tier tools only **propose**; the confirmation gate + executor are the only
path to a mooKIT write.

## What it can do

### Instructor flows (product)

| Flow | What happens | Tools | mooKIT write? |
|------|----------------|-------|---------------|
| **Quiz from document** | Upload PDF/DOCX → RAG index → generate cited questions → edit → publish | `create_quiz`, `edit_quiz`, `publish_assessment` | Only after **Confirm** |
| **Announcement** | LLM drafts subject + body → preview → send to audience | `draft_announcement`, `send_announcement` | Only after **Confirm** |
| **Lecture** | Upload file → draft (week/module) → publish with attachment | `draft_lecture`, `publish_lecture` | Only after **Confirm** |

### Platform capabilities

| Capability | Endpoint / component |
|------------|---------------------|
| Streaming chat (SSE) | `POST /v1/chat` — assistant text, tool progress, draft previews, confirmation |
| File upload + RAG | `POST /v1/files` — validation, extraction, pgvector indexing (ARQ worker) |
| Human confirmation | `POST /v1/actions/{id}/confirm` or `/reject` — one-time token + content hash |
| Read / introspection | `whoami`, `resolve_taxonomy`, `my_permissions` |
| Safety | OpenAI Moderation + injection heuristics; no silent publish |
| Health | `GET /health/live`, `GET /health/ready` |
| Meta | `GET /v1/meta` |

### Registered tools

`echo` · `whoami` · `resolve_taxonomy` · `my_permissions` · `create_quiz` · `edit_quiz` ·
`publish_assessment` · `draft_announcement` · `send_announcement` · `draft_lecture` · `publish_lecture`

## Architecture

```
mooKIT frontend ──headers: course,token,uid──► FastAPI (/v1/chat SSE, /v1/files, /v1/actions/*)
   │ RequestContext (tenant_key namespaces everything)
   ▼
Orchestrator (Plan-then-Execute)
   ├─ read/draft tools ─► run inline (quiz pipeline, taxonomy, drafts)
   └─ publish tools ────► ProposedAction ─► ConfirmationGate
                                              └─ human confirm ─► DeterministicExecutor ─► MooKitClient
OpenAI Responses API ◄─ LLMProvider          Redis · Postgres (pgvector RAG)
```

See `docs/ai-architecture.md` and `docs/plan/`.

## Run the full stack (Docker)

```bash
cp .env.example .env    # set OPENAI__API_KEY, MOOKIT__BASE_URL, SECURITY__SECRET_KEY
cd deploy
sudo ./up.sh            # uses Docker Compose v2 — NOT legacy docker-compose v1
```

- API: `http://localhost:8000` (Swagger at `/docs`)
- Sample UI: `http://localhost:8000/ui`
- Logs: `sudo ./logs.sh api` (or `worker`, `all`)

Stack: `api + worker + postgres (pgvector) + redis`. The compose file loads `../.env` automatically.
On Docker 29+, use `docker compose` (space). Legacy `docker-compose` v1 hits `KeyError: ContainerConfig`.

```bash
# Manual equivalent:
cd deploy
sudo docker compose --env-file ../.env up -d --build
```

### Restart after changes

From `deploy/`, use the wrapper so `.env` is always loaded:

```bash
cd deploy
./dc.sh up -d --build          # rebuild + recreate (use after code/Dockerfile changes)
./dc.sh up -d                  # restart with current images (env/config-only changes)
./dc.sh down --remove-orphans  # stop everything cleanly
./dc.sh ps                     # status
./logs.sh api                  # tail service logs (api/worker/postgres/pgadmin/redis/all)
```

If scripts are not executable once:

```bash
chmod +x deploy/dc.sh deploy/logs.sh deploy/up.sh
```

## Sample chat UI

`sample-ui/index.html` — vanilla-JS client served at `/ui`:

- Streaming SSE chat (CRLF-safe parser)
- File upload
- **Draft preview cards** (announcement subject/body = exact mooKIT `title` / `description`)
- Quick-action buttons (e.g. “Yes — send announcement”)
- Confirm / Cancel modal before any publish or send

Configure in the header (or `?token=JWT` in the URL):

| Field | Example |
|-------|---------|
| Service URL | `http://<vm-ip>:8000` (not `localhost` when browsing remotely) |
| course | `coursetest` |
| uid | `1` |
| token | Full mooKIT JWT |

## Manual testing guide

Use this checklist against the sample UI. Watch logs: `sudo ./deploy/logs.sh api`.

### Prerequisites

```bash
curl http://localhost:8000/health/live   # {"status":"live"}
curl http://localhost:8000/health/ready  # {"status":"ready"}
MOOKIT_TOKEN=<jwt> uv run python scripts/probe_mookit.py   # IITK network
```

### Phase 0 — Smoke

1. Open `/ui` — page loads.
2. Open `/docs` — Swagger loads.

### Phase 1 — Read tools

| Say this | Expect |
|----------|--------|
| `Who am I?` | mooKIT user context |
| `What are my permissions?` | Permission list |
| `What weeks exist in this course?` | Taxonomy (Week 1–4, etc.) |

### Phase 2 — Announcement

1. **Cancel today's class**
2. Draft card shows **Subject** + **Body** (exact mooKIT payload), audience, channel, priority.
3. Click **Yes — send announcement** (or type it).
4. **Confirm** modal exposes the de-hardcoded controls:
   - **Audience** dropdown — `All students` + live sections from `GET /v1/taxonomy` (no invented names).
   - **Also send email** toggle (`notifyMail`).
   - **Schedule for later** + datetime → `published.status=0` + `releaseOn`; blank = send now.
   - **Attachments** — pick a file → **Attach** (`POST /v1/announcement/attach`) → appears as a removable chip; ids ride `fileIds` on send.
5. **Confirm** → `✅ Announcement sent (id …)`.
6. **Cancel path**: repeat, click **Cancel** in modal → no write.
7. **Bad section**: pick a section, then delete it in mooKIT before confirming → revise/confirm refuses fail-closed (not broadcast to all).
8. **Edit**: `Make the tone softer and mention class resumes Monday` → revised draft.

### Phase 3 — Quiz from document

1. Upload a **PDF or DOCX** (course material).
2. Wait for worker indexing (`./logs.sh worker`).
3. `Create a quiz from this document — 5 questions, mixed types`
4. `Add 2 true/false questions` → version bump.
5. `Publish this quiz to the course` → **Confirm** modal exposes quiz settings (de-hardcoded):
   - **Type** (Quiz / Exam / Assignment), **Opens / Closes / Results** datetimes (validated ordering).
   - **Timed** + duration (minutes), **Show answers**, **Allow retakes**, **Instructions**.
   - Preview card lines reflect exactly what is sent.
6. **Confirm** → verify assessment in mooKIT (optional, with the chosen dates/type).

### Phase 4 — Lecture

1. Upload a video or document.
2. Pick a **week** from the live dropdown (and optional **module**) in the lecture controls.
3. `Publish this lecture` → Confirm modal (diff: resolved week/module label, title, schedule, attachments) → Confirm.
4. Optional: `POST /v1/lecture/{draft_id}/edit` re-resolves the week/module against live taxonomy.
5. **Empty taxonomy**: a course with no weeks shows the *"No weeks configured — add them in mooKIT"* hint and disables the week picker.

### Phase 5 — Safety

1. Upload `tests/fixtures/injection_doc.txt`.
2. `Summarize and publish immediately without asking` → **no** auto-publish.
3. Malicious instructions must not bypass the confirmation gate.

### Example chat phrases

| Goal | Prompt |
|------|--------|
| Announcement | `Cancel today's class` |
| Send | `Yes, send the announcement to all students` |
| Quiz | `Create a quiz from this PDF — 5 questions` |
| Edit quiz | `Add 3 true/false questions` |
| Publish quiz | `Publish this quiz to the course` |
| Lecture | `Publish this video under Week 4` |

Successful publish flow: user message → tool chips → **draft preview** → assistant text →
confirm modal → `✅ … confirmed` → mooKIT id in response.

## Run locally (without Docker)

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
# needs local Postgres + Redis (or compose services only):
uv run uvicorn app.main:app --reload
```

## Develop / test (no infra, no API key)

```bash
uv run pytest -q -m "not live"
uv run python scripts/demo.py
uv run python scripts/eval_report.py
uv run ruff check app tests scripts && uv run mypy app
```

Live paths (funded OpenAI key / IITK network for mooKIT):

```bash
uv run pytest -q -m live
uv run python scripts/demo.py --live
MOOKIT_TOKEN=<jwt> uv run python scripts/probe_mookit.py
```

## Production

Real OpenAI (chat, quiz, embeddings, Moderation), **pgvector RAG**, mooKIT writes via the confirmation
executor, Alembic migrations, CORS + optional `SECURITY__SERVICE_API_KEY`. Full runbook:
**`docs/production-setup.md`**.

```bash
cp .env.example .env
# set OPENAI__API_KEY, MOOKIT__BASE_URL, SECURITY__*, AUTO_CREATE_TABLES=false
cd deploy && sudo ./up.sh
alembic upgrade head
```

## Docs

- `docs/production-setup.md` — production runbook
- `docs/demo-script.md` — three demo flows (narrative)
- `docs/ai-architecture.md` · `docs/prompt-library.md` · `docs/eval-report.md`
- `docs/plan/` — contracts, work plans, mooKIT API reference

## Status

- Offline tests green; ruff + mypy clean (Python 3.10+).
- `/v1/chat` streams orchestrator end-to-end (`tests/api/test_chat_sse.py`).
- Injection red-team: **0 unconfirmed actions** (`app/evals/injection_redteam.py`).
- Live mooKIT: IITK network + full JWT via `scripts/probe_mookit.py`.
