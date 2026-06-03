# 02 — Architecture & Tech Stack

## System architecture

```
 mooKIT instance ──HTTP(headers: course,token,uid + body: instanceId,courseId,userId,sessionId)──┐
                                                                                                   ▼
┌──────────────────────────── AI Assistant Service (FastAPI, stateless) ──────────────────────────┐
│  API/SSE layer (sse-starlette)                                                                    │
│     │ chat · files · actions/confirm · sessions                                                   │
│     ▼                                                                                             │
│  Tenant context (resolved per request; tenant_key namespaces EVERYTHING)                          │
│     ▼                                                                                             │
│  ┌─ Orchestrator (Responses API loop) ─────────────┐   ┌─ Memory ───────────────────────────┐    │
│  │  Plan-then-Execute: decide tools BEFORE reading  │   │ Transcript (buffer+summary)         │    │
│  │  untrusted content; parallel_tool_calls=False    │◀─▶│ Artifact registry (typed, versioned,│    │
│  │  for mutating tools; structured outputs          │   │ provenance) + focus stack           │    │
│  └───────┬───────────────────────────┬─────────────┘   └─────────────────────────────────────┘    │
│          │ read/draft tools           │ PUBLISH tools = PROPOSE only                               │
│          ▼                            ▼                                                            │
│  ┌─ Tool registry (risk-tiered) ─┐   ┌─ Confirmation gate (NON-LLM, deterministic) ──────────┐    │
│  │ assessment · announcement ·    │   │ token bound to (action,targetId,content-hash); render │    │
│  │ lecture · common(users/perms)  │   │ faithful preview; only this service executes the call │    │
│  └───────┬────────────────────────┘   └───────────────────────┬───────────────────────────────┘  │
│          ▼                                                     ▼                                   │
│  ┌─ Quarantined extraction ─┐  ┌─ mooKIT client ─┐  ┌─ Guardrails ─┐  ┌─ Audit log ─┐  ┌─ ARQ ──┐  │
│  │ sandbox, magic-byte, RAG │  │ header forward, │  │ injection/   │  │ append-only │  │ workers│  │
│  │ chunk+cite               │  │ envelope unwrap │  │ moderation   │  │ per-tenant  │  │ +Redis │  │
│  └──────────────────────────┘  └────────┬────────┘  └──────────────┘  └─────────────┘  └────────┘  │
└──────────────────────────────────────────┼────────────────────────────────────────────────────────┘
                                            ▼ mooKIT REST (55 eps)        ▼ OpenAI Responses API
```

**Core idea:** an OpenAI **Responses-API tool-calling loop** where each mooKIT capability is a *tool*.
Tools are classified **read / draft / publish**. Read & draft tools auto-execute; **publish tools are gated
behind a deterministic two-phase confirm** (propose → faithful preview → human confirms → non-LLM executor
calls mooKIT). This satisfies the hard rule that nothing publishes/sends without confirmation.

## Project structure
```
ai-assistant/
├─ app/
│  ├─ main.py                 # FastAPI app, routers, lifespan, middleware
│  ├─ config.py               # pydantic-settings (provider keys, limits, instance allowlist)
│  ├─ contracts/              # the 7 shared interfaces (frozen at CP1)
│  ├─ api/                    # chat.py files.py confirm.py sessions.py health.py
│  ├─ core/                   # orchestrator.py memory.py reference_resolver.py confirmation.py
│  │                          # context.py security_infra.py  + prompts/
│  ├─ llm/                    # base.py openai_provider.py events.py
│  ├─ tools/                  # registry.py assessment.py announcement.py lecture.py common.py
│  ├─ gen/                    # quiz/{rag,prompting,schemas,verify,distractors,rubric}.py
│  │                          # announcement.py lecture_meta.py
│  ├─ preview/                # render.py (PreviewRender builders)
│  ├─ mookit/                 # client.py schemas.py errors.py registry.py
│  ├─ auth/                   # permissions.py
│  ├─ files/                  # upload.py validate.py extract.py rag_index.py (sandbox)
│  ├─ store/                  # session_store.py artifact_registry.py db.py redis.py
│  ├─ workers/                # arq_app.py tasks.py progress.py
│  ├─ audit/                  # logger.py
│  ├─ obs/                    # tracing.py cost.py
│  └─ evals/                  # quiz_quality.py hallucination.py injection_redteam.py
├─ sample-ui/                 # chat + file drop + editable quiz preview + confirm dialog
├─ tests/
├─ deploy/                    # Dockerfile docker-compose.yml k8s/*.yaml
├─ docs/
└─ openapi.mookit.json        # pinned snapshot of the live spec
```

## Tech stack (concrete)
| Concern | Choice | Notes |
|---|---|---|
| Runtime | Python 3.12, FastAPI, uvicorn (+gunicorn worker mgmt) | async throughout |
| HTTP → mooKIT/LLM | single shared `httpx.AsyncClient` via `lifespan` | `http2=True`, explicit `Limits` + `Timeout(connect=5,read=60,write=10,pool=5)` |
| LLM | `openai` SDK, **Responses API**; `responses.parse` for strict Structured Outputs | behind `LLMProvider` ABC (swappable per spec §12); prompt caching (static-first, `prompt_cache_key`) |
| Streaming | `sse-starlette` v3.4.x | `ping≈15s`; abort on `request.is_disconnected()` |
| Async jobs | **ARQ + Redis** | asyncio-native; separate worker Deployment; progress via Redis → SSE |
| DB | Postgres, **shared-schema with `tenant_key`** | RLS `FORCE` as safety net; SQLite for dev |
| Cache/queue/bus | Redis | session cache, job state, **SSE pub/sub backplane**, rate-limit counters |
| File parsing | pypdf/pdfplumber, python-docx, python-pptx, openpyxl, pandas | magic-byte sniff + sandboxed extraction |
| Security tooling | OpenAI Guardrails (+ tool guardrails) + Moderation; spotlighting | |
| Observability | OpenTelemetry GenAI conventions (wrapped) + **Langfuse** | per-tenant token/cost attribution |
| Resilience | `tenacity` retries, `pybreaker`/`pyresilience` circuit breakers, provider fallback, Redis rate-limit | order: rate-limit → breaker → retry → timeout |
| Config | `pydantic-settings` v2 + secret manager | per-instance registry table |
| Sample UI | React (Vite) | chat, file drop, editable quiz preview, audience-chip confirm |
| Deploy | Docker + compose (dev); stateless pods + HPA, **no sticky sessions** | liveness/readiness/startup probes; proxy buffering off for SSE; **CPU only, no GPU** |

## Service-exposed API (our endpoints)
| Endpoint | Purpose |
|---|---|
| `POST /v1/chat` | Conversation turn; SSE stream (assistant tokens, tool progress, `pending_confirmation`) |
| `POST /v1/files` | Upload → validate → sandboxed-extract → index; returns `fileId` + artifact |
| `POST /v1/actions/{id}/confirm` · `/reject` | Complete/abort a gated publish action |
| `GET /v1/sessions/{id}` | Conversation history |
| `GET /v1/meta` · `/health/{live,ready,startup}` | Instance allowlist/limits; health probes |
