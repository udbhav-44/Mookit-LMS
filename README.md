# mooKIT AI Assistant for Instructors

A standalone, multi-tenant microservice that lets instructors drive mooKIT through natural language:
**generate grounded quizzes from documents, draft/send announcements, and publish lectures** — always
with a deterministic human confirm before anything publishes or sends.

> *"We make suggestions. You make decisions."*

This repository is the **integrated product** of two tracks that meet at 7 shared contracts
(`app/contracts/`):

- **Dev A — Platform / Integration / Security** (`app/main.py`, `app/api/*`, `app/mookit/*`,
  `app/store/*`, `app/core/{context,confirmation,executor,rate_limit,security_infra}.py`,
  `app/files/*`, `app/workers/*`, `deploy/*`): FastAPI app, SSE, multi-tenancy, the typed `MooKitClient`,
  Redis/Postgres stores, sandboxed file ingestion + RAG, the confirmation gate + deterministic executor,
  audit, observability, rate-limiting, and deployment.
- **Dev B — AI Brain & Domain Logic** (`app/core/{orchestrator,memory,reference_resolver,prompts,
  guardrails}.py`, `app/llm/*`, `app/tools/*`, `app/gen/*`, `app/preview/*`, `app/evals/*`): the
  Plan-then-Execute orchestrator, two-channel memory, the RAG-grounded quiz pipeline, the three domain
  tool modules, `ProposedAction`/`PreviewRender`, prompt/safety design, and the eval harness.

The Dev B AI brain is wired onto the platform in `app/core/wiring.py` (set as `app.state.orchestrator`),
and `POST /v1/chat` streams its events over SSE. Publish-tier tools only ever **propose**; the
confirmation gate + executor are the only path to a mooKIT write.

## Architecture (one screen)

```
mooKIT frontend ──headers: course,token,uid──► FastAPI (/v1/chat SSE, /v1/files, /v1/actions/*)
   │ RequestContext (tenant_key namespaces everything)
   ▼
Orchestrator (Plan-then-Execute, generic LLMEvent stream)
   ├─ read/draft tools ─► run inline (quiz pipeline, taxonomy, drafts)
   └─ publish tools ────► ProposedAction ─► ConfirmationGate (one-time token, content-hash)
                                              └─ human confirm ─► DeterministicExecutor ─► MooKitClient
OpenAI Responses API ◄─ LLMProvider          Redis (sessions/RAG/rate-limit) · Postgres (durable)
```

See `docs/ai-architecture.md` (AI side) and `docs/plan/` (full plan + both work plans).

## Run the full stack (Docker)

```bash
cp .env.example .env            # set OPENAI__API_KEY (or OPENAI_API_KEY); set MOOKIT__BASE_URL
docker compose -f deploy/docker-compose.yml up --build
# API:    http://localhost:8000   (docs at /docs)
# Sample chat UI: http://localhost:8000/ui
```

The stack is `api + worker + postgres + redis`. Tables are created on startup; uploads are
sandboxed-extracted and RAG-indexed by the worker.

## Run locally (without Docker)

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
# needs a local Postgres + Redis (or use the compose services), then:
uv run uvicorn app.main:app --reload
```

## Develop / test the AI brain solo (no infra, no key)

The AI brain runs fully against in-process fakes (`tests/fakes/`):

```bash
uv run pytest -q -m "not live"      # 154 tests, no Postgres/Redis/OpenAI needed
uv run python scripts/demo.py       # human-readable walkthrough of the 3 flows + injection red-team
uv run python scripts/eval_report.py
uv run ruff check app tests scripts && uv run mypy app
```

Live paths (need a funded OpenAI key / IITK network):

```bash
uv run pytest -q -m live                 # one real streamed turn (needs OPENAI_API_KEY)
uv run python scripts/demo.py --live     # real quiz generation
MOOKIT_TOKEN=<jwt> uv run python scripts/probe_mookit.py   # live mooKIT reads (run on IITK network)
```

## Sample chat UI
`sample-ui/index.html` — a zero-build vanilla-JS chat client (streaming, file upload, confirm dialog
with audience chip / diff). Served at `/ui` when the app runs. The richer editable quiz-preview React
component lives in `sample-ui/quiz-preview/`.

## Docs
- `docs/ai-architecture.md` · `docs/demo-script.md` · `docs/prompt-library.md` · `docs/eval-report.md`
- `docs/plan/` — overview, the 7 shared contracts, both dev work plans, the Dev B execution plan,
  the mooKIT API reference, research synthesis.

## Status
- 154 offline tests green; ruff + mypy clean (Python 3.10+).
- `/v1/chat` streams the orchestrator end-to-end (verified with `tests/api/test_chat_sse.py`).
- Injection red-team: **0 unconfirmed actions** (`app/evals/injection_redteam.py`).
- Live mooKIT writes wired through the executor; verify on the IITK network with `scripts/probe_mookit.py`
  (the dev token in `docs/details.md` appears truncated — supply a full JWT).
