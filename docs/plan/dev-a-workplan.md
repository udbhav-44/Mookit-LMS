# Dev A — Work Plan: Platform, Integration & Security Infrastructure

**Role:** Owns the *trust + plumbing* layer — everything that makes the AI service a safe, multi-tenant,
production microservice that talks to mooKIT and never publishes without a deterministic human confirm.

**Mental model:** Dev A can build and test the entire `request → mooKIT → confirm → audit` path using a
*stub tool*, with zero dependency on the AI brain. The AI brain (Dev B) plugs into the seams defined in
[05-shared-contracts.md](05-shared-contracts.md).

**Owned packages**
```
app/main.py app/config.py
app/api/            chat.py files.py confirm.py sessions.py health.py
app/core/context.py app/core/confirmation.py app/core/security_infra.py
app/mookit/         client.py schemas.py errors.py registry.py
app/auth/           permissions.py
app/files/          upload.py validate.py extract.py rag_index.py   (extraction sandbox)
app/store/          session_store.py artifact_registry.py db.py redis.py
app/workers/        arq_app.py tasks.py progress.py
app/audit/          logger.py
app/obs/            tracing.py cost.py
deploy/             Dockerfile docker-compose.yml k8s/*.yaml
sample-ui/          (integration wiring: SSE client, file drop, confirm dialog plumbing)
```

---

## Cross-cutting principles Dev A must enforce everywhere
- **`tenant_key` namespaces *everything*** — every DB row, every Redis key (`{tenant_key}:...`), every log
  line, every cache entry. Tenant derived from the authenticated session **only**, never from request body
  or document content.
- **Forwarded credentials are request-scoped** — `course`/`token`/`uid` are passed to mooKIT and never
  persisted, never logged raw, never cached beyond the request.
- **The confirmation gate is a hard wall** — publish/send mooKIT calls are physically unreachable by the
  model loop. The model can only *propose*; only Dev A's non-LLM executor calls the write endpoints.
- **Fail fast, degrade gracefully** — explicit timeouts, retries on idempotent failures, circuit breakers
  per dependency, friendly typed errors surfaced to the UI.

---

## P0 — Foundations  → checkpoint **CP1**
Goal: app boots, contracts frozen, a hello-world chat turn streams end-to-end (with Dev B's bare loop).

| # | Task | Detail |
|---|---|---|
| A0.1 | Repo + tooling | Poetry/uv, ruff, mypy, pytest, pre-commit; `app/` layout; `pyproject` pins (`openai`, `fastapi`, `uvicorn`, `httpx[http2]`, `sse-starlette>=3.4`, `arq`, `pydantic>=2`, `pydantic-settings`, `tenacity`, `pybreaker`, `sqlalchemy`/`asyncpg`, `redis`). |
| A0.2 | Config | `pydantic-settings` v2: nested settings (db, redis, openai, mookit, limits). `SecretStr` for keys. Validate at startup → fail fast. `.env` for dev only; secret-manager path documented for prod. |
| A0.3 | **Freeze shared contracts** | Implement `app/contracts/` (the 7 interfaces). Pair with Dev B to lock JSON-Schema dialect for tool params (strict mode rules). **This is the gating deliverable of P0.** |
| A0.4 | App skeleton + lifespan | FastAPI app; `lifespan` creates the single shared `httpx.AsyncClient` (`http2=True`, explicit `Limits(max_connections=200, max_keepalive=50)`, `Timeout(connect=5, read=60, write=10, pool=5)`), Redis pool, DB engine; stored on `app.state`, injected via `Annotated[..., Depends(...)]`. |
| A0.5 | `MooKitClient` (read paths) | Generic `call()` injecting `course`/`token`/`uid`; unwrap `{success,code,message,data}`; map `{success:false,error}` → typed exceptions. Pin `openapi.mookit.json` in repo; generate Pydantic `schemas.py`. Implement `get_permissions`, `users/me`, `list_taxonomy` first. |
| A0.6 | `FakeMooKitClient` | Canned responses for every endpoint Dev B needs → unblocks Dev B immediately. |
| A0.7 | Tenant + DB schema | Postgres shared-schema; **every table has `tenant_key`**; tables: `sessions`, `messages`, `artifacts`, `audit_log`, `pending_actions`, `file_meta`, `instance_registry`. SQLite fallback for dev. |
| A0.8 | In-memory stores | `SessionStore` + `ArtifactRegistry` in-memory impls (Redis-backed versions come in P1). |
| A0.9 | Health endpoints | `/health/live` (no deps), `/health/ready` (DB+Redis), `/health/startup`. |

**CP1 exit:** contracts merged; `POST /v1/chat` streams an SSE `assistant_delta` from Dev B's bare loop through Dev A's API layer; `MooKitClient.get_permissions` works against the live test instance.

---

## P1 — Core request loop  → checkpoint **CP2**
Goal: real multi-turn chat with one read-only tool, tenant-isolated, audited, streamed.

| # | Task | Detail |
|---|---|---|
| A1.1 | API/SSE layer | `POST /v1/chat` returns `EventSourceResponse`; `ping≈15s`; `await request.is_disconnected()` in the generator to abort work + stop LLM spend. Implement the full SSE event schema (Contract 6). Create DB sessions *inside* the generator (not as a dependency — dependency-scoped sessions close before a long stream finishes). Handle `asyncio.CancelledError` for cleanup. |
| A1.2 | `RequestContext` middleware | Parse `course`/`token`/`uid` headers + body `{instanceId,courseId,userId,sessionId}`; resolve `tenant_key`; mint `request_id`; fetch + cache `permissions`. Reject unauthenticated/cross-instance requests. |
| A1.3 | Auth + permissions | `app/auth/permissions.py`: cache `GET /user_permissions/allowed` per session; expose `require(action, resource)` helper used by the confirmation gate and tool dispatch. |
| A1.4 | Redis-backed stores | Real `SessionStore` (transcript in Redis with TTL; summary slot) + `ArtifactRegistry` (Redis hot + Postgres durable). Keys prefixed `{tenant_key}:`. Provide the focus-stack ops. |
| A1.5 | Audit logger | Append-only `audit_log`: `{instance_id,user_id,session_id,request_id,action,tool,status,timestamp,model,tokens,cost}`. Redact prompt/response per retention policy. Separate from observability traces. |
| A1.6 | ARQ scaffolding | `arq_app.py` worker + Redis broker; a demo task; **progress bridge**: task writes `{tenant_key}:job:{id}:progress` → SSE progress endpoint reads/subscribes and emits `tool_progress`. |
| A1.7 | Sessions API | `GET /v1/sessions/{id}` history; `GET /v1/meta` (instance allowlist, limits). |

**CP2 exit:** multi-turn conversation works through Dev B's orchestrator + Dev A's stores; a read-only tool round-trips; audit rows written; tenant isolation unit-tested (two tenants can't see each other's sessions/artifacts).

---

## P2 — Files + RAG ingestion  → checkpoint **CP3**
Goal: a PDF becomes safe, chunked, retrievable content with citations available to Dev B's quiz pipeline.

| # | Task | Detail |
|---|---|---|
| A2.1 | Upload API | `POST /v1/files` multipart → returns `fileId` + artifact (`type=uploaded_file`). Configurable max size. |
| A2.2 | **Validation** | Validate by **magic bytes + container parse**, not extension/MIME (both forgeable): PDF `%PDF`, DOCX/PPTX/XLSX = ZIP `PK\x03\x04` then confirm OOXML. Enforce size + page/slide caps + **zip-bomb / decompression limits**. Reject corrupted/unsupported gracefully (typed error → UI). AV scan hook. |
| A2.3 | **Sandboxed extraction** | Parse in an **isolated, network-egress-disabled** sandbox (container/gVisor/subprocess w/ dropped privileges + CPU/mem/time limits) — parser libs are an RCE surface. Strip active content (macros, OLE, external/remote-template refs; do **not** fetch external resources). Extract text; treat extracted text as **untrusted data**. Formats: PDF, DOCX, PPT/PPTX, TXT, XLSX, CSV. |
| A2.4 | Store + serve | Originals stored outside web root, non-guessable names, non-executable content type; promote to permanent only after passing checks. |
| A2.5 | RAG index | Chunk extracted text; build a per-document, **tenant-namespaced** retrievable index (pgvector or in-proc for MVP). Expose `retrieve(ctx, doc_artifact_id, query, k) -> [{span, text, locator}]` so Dev B can cite source spans. Authorization enforced at retrieval time (never return another tenant's chunks). |
| A2.6 | Large-file path | Extraction + indexing run as an ARQ job with progress events for big uploads. |

**CP3 exit:** upload a real PDF → validated, sandboxed-extracted, chunked, retrievable; Dev B's pipeline pulls cited spans; oversized/corrupt/zip-bomb files rejected cleanly.

---

## P3 — Confirmation gate + mooKIT write endpoints  → checkpoint **CP4**
Goal: all three flows publish to mooKIT **only** after a deterministic, content-bound human confirm.

| # | Task | Detail |
|---|---|---|
| A3.1 | **Confirmation gate** | `app/core/confirmation.py`: when the orchestrator yields a `ProposedAction`, persist it in `pending_actions` and emit `pending_confirmation`. Mint a **one-time token bound to `(action, target_ref, content_hash)`**. The model loop cannot call write endpoints — only this module can. |
| A3.2 | Confirm/reject API | `POST /v1/actions/{action_id}/confirm` and `/reject`. On confirm: re-validate permissions, verify the token + that the artifact's current `content_hash` **still matches** (re-drafting voids the token → blocks "approve benign, swap malicious"), then execute the mooKIT write. On reject: discard. |
| A3.3 | Deterministic executor | The non-LLM executor maps `ProposedAction` → typed `MooKitClient` write calls. **All recipients/targets resolved server-side** from session/permissions — never from model/document text. |
| A3.4 | mooKIT write helpers | Implement typed writes: `create_assessment` / sections / `add_question` / publish (`PUT ...published.status=1`); `create_announcement`; `upload_file`; `create_lecture` + `attach_course_resource` + schedule; `list_taxonomy` for week/module resolution. Match live payloads exactly (see [09-mookit-api-reference.md](09-mookit-api-reference.md)). |
| A3.5 | Bulk question job | Creating many questions = ARQ job with `tool_progress` ("12/30 created"). Idempotency keys so retries don't double-create. |
| A3.6 | Risk-tiered routing | read/draft tools auto-execute; only `publish`-tier produces a gate. Keep high-risk prompts rare (fights approval fatigue). |

**CP4 exit:** quiz, announcement, and lecture each go draft → preview → confirm → live mooKIT object; rejecting discards; editing after approval invalidates the old token; nothing publishes without confirm (verified by test).

---

## P4 — Hardening  → checkpoint **CP5**
Goal: secure, observable, resilient, multi-instance.

| # | Task | Detail |
|---|---|---|
| A4.1 | Multi-tenant isolation tests | Adversarial tests: cross-tenant session/artifact/cache/log access must all fail. Verify cache keys + log scoping. (Optional RLS `FORCE ROW LEVEL SECURITY` as a safety net — mind PgBouncer transaction-pooling: use `SET LOCAL`/`set_config(...,true)`.) |
| A4.2 | Guardrails plumbing | Wire OpenAI Guardrails + Moderation as input/output/tool guardrails at the boundary (Dev B owns the prompt-level policy; Dev A owns the infra hooks). Deterministically strip/blocks model-generated outbound links + markdown images in published content (anti-exfil). |
| A4.3 | Resilience | `tenacity` retries (429/5xx + connect/read timeouts, full jitter, honor `Retry-After`; idempotency keys on POSTs); per-dependency circuit breakers (`pybreaker`/`pyresilience`); provider/model fallback chain; Redis-backed **per-tenant rate limiting** (token bucket). Compose order: rate-limit → breaker → retry → timeout. |
| A4.4 | Observability | OpenTelemetry GenAI conventions (wrap them — still experimental) + **Langfuse** traces; per-tenant **token/cost** attribution + dashboards; correlation `request_id` propagated through SSE + ARQ. |
| A4.5 | Deployment | Dockerfile (slim), docker-compose (service + Postgres + Redis + worker); k8s manifests: stateless pods, **HPA** (CPU / active-connections), **no sticky sessions** (Redis pub/sub backplane so any pod serves any SSE stream), liveness/readiness/startup probes, graceful SIGTERM drain (stop new streams, finish in-flight within grace period), proxy buffering off + idle timeout > ping for SSE. **CPU instance, no GPU.** |
| A4.6 | Instance registry | `instance_registry` table mapping `instance_id` → mooKIT base URL + per-instance config (model, limits, retention). Pluggable; documented format. |

**CP5 exit:** security review passes; load test sustains concurrent multi-instance traffic; isolation + resilience tests green; cost dashboard live.

---

## P5 — Deliverables  → checkpoint **CP6**
| # | Task |
|---|---|
| A5.1 | **Deployment guide** + **setup instructions** (local + prod, env vars, secrets, scaling). |
| A5.2 | **API documentation** for the service's own exposed endpoints (chat, files, confirm, sessions). |
| A5.3 | Infra runbook (health, dashboards, alerts, on-call basics). |
| A5.4 | Sample-UI integration polish (SSE client, file drop, confirm dialog wired to `pending_confirmation`). |

---

## Dev A acceptance checklist (definition of done)
- [ ] Every storage/cache/log entry is `tenant_key`-scoped; cross-tenant access tests fail closed.
- [ ] Forwarded creds never persisted/logged raw.
- [ ] No mooKIT write endpoint is reachable except via the confirmation executor.
- [ ] Confirm tokens are one-time and content-hash-bound; stale-hash confirms rejected.
- [ ] File uploads validated by magic bytes; extraction sandboxed + network-isolated; zip-bombs rejected.
- [ ] SSE survives proxies (heartbeat), aborts on client disconnect, drains on shutdown.
- [ ] Long tasks run on ARQ workers with live progress; idempotent on retry.
- [ ] Retries/breakers/rate-limits/fallbacks in place; explicit timeouts everywhere.
- [ ] Audit log complete; per-tenant cost/traces visible.
- [ ] Stateless pods autoscale without sticky sessions.

## Key dependencies / handoffs
- **Needs from Dev B:** `LLMProvider` impl (to test streaming), `Tool` instances (real risk tiers), `ProposedAction`/`PreviewRender` shapes honored.
- **Gives to Dev B:** `RequestContext`, `MooKitClient` (+ `FakeMooKitClient`), `SessionStore`/`ArtifactRegistry`, RAG `retrieve()`, confirmation gate, SSE plumbing.
