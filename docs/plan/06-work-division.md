# 06 — Work Division (Dev A / Dev B)

Full task-level detail in [dev-a-workplan.md](dev-a-workplan.md) and [dev-b-workplan.md](dev-b-workplan.md).
This is the one-page ownership map.

## Dev A — Platform, Integration & Security infrastructure
*The trust + plumbing layer.* Can build/test the entire `request → mooKIT → confirm → audit` path with a
stub tool, with zero dependency on the AI brain.

- FastAPI app skeleton, lifespan, DI, config (`pydantic-settings` + per-instance registry)
- API/SSE layer (`sse-starlette`, heartbeat, disconnect handling, SSE event schema impl)
- Multi-tenant foundation: Postgres schema, `tenant_key` scoping, RLS, Redis namespacing
- `MooKitClient` + Pydantic schemas (from pinned OpenAPI), envelope unwrap, error mapping
- Auth/permission layer (`/users/me`, `/user_permissions/allowed`), `RequestContext`
- **Confirmation gate** (token service, content-hash, deterministic executor)
- File upload + validation + **sandboxed extraction** + RAG chunking/indexing infra
- `SessionStore`/`ArtifactRegistry` implementations (Redis + Postgres)
- ARQ worker setup + progress→SSE bridge
- Audit logging, Langfuse/OTel observability, resilience (retries/breakers/rate-limit)
- Sample-UI integration (file drop, SSE wiring, confirm dialog plumbing)
- Deployment: Docker/compose, k8s manifests, probes, scaling

## Dev B — AI Brain & Domain Logic
*The intelligence + product layer.* Can build/test the agent + quiz pipeline against a `FakeMooKitClient`
and in-memory `SessionStore`.

- `LLMProvider` (OpenAI Responses API) + structured-output plumbing + prompt caching
- **Orchestrator** (Plan-then-Execute loop, tool dispatch, streaming event emission)
- Two-channel **memory** (transcript compaction + artifact registry) + focus-stack reference resolution
- `Tool` registry + the three domain modules (assessment/announcement/lecture) + `common` (users/perms/taxonomy)
- **Quiz pipeline:** RAG grounding (PS4), per-type schemas + validation, **misconception distractors** +
  quality check, **multi-stage verification**, rubric generation, difficulty/Bloom/reading-level knobs
- Announcement & lecture draft + metadata/title generation
- `ProposedAction` construction + faithful `PreviewRender`
- Spotlighting / instruction-hierarchy prompt design; guardrails integration at the model boundary
- System prompts, persona, safety policy text
- Sample UI: editable quiz-preview component + provenance/flag affordances
- Eval harness: quiz-quality / hallucination / injection red-team

## Why this split works
The two tracks are decoupled by the [7 shared contracts](05-shared-contracts.md). They meet only at the six
[checkpoints](07-timeline-and-checkpoints.md). The **confirmation gate (P3)** is the single tight interlock
— `ProposedAction` (Dev B) ⇄ deterministic executor (Dev A) — so schedule a joint working session at the
P2→P3 boundary.

## Handoffs at a glance
| From | To | What |
|---|---|---|
| Dev A → Dev B | | `RequestContext`, `MooKitClient` (+ `FakeMooKitClient`), `SessionStore`/`ArtifactRegistry`, RAG `retrieve()`, confirmation gate, guardrail hooks, SSE plumbing |
| Dev B → Dev A | | `LLMProvider` impl, `Tool` instances (correct risk tiers), `ProposedAction` + `PreviewRender`, prompt/safety policy, quiz-preview UI component |
