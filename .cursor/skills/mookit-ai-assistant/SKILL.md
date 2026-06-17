---
name: mookit-ai-assistant
description: Develop and extend the mooKIT AI Assistant microservice — orchestrator, tools, quiz pipeline, confirmation gate, RAG, and mooKIT integration. Use when working in this repo, adding tools, modifying publish flows, debugging SSE chat, or touching app/core, app/tools, app/gen, app/api, or app/store.
---

# mooKIT AI Assistant

Standalone FastAPI microservice: instructors drive mooKIT via natural language. Quizzes, announcements, lectures — always draft first, human confirm before any write.

## Non-negotiable invariant

**The LLM loop never writes to mooKIT.**

```
read/draft tools  → Tool.run() → ToolResult → continues SSE turn
publish tools     → ProposedAction → ConfirmationGate → pending_actions (PG)
confirm endpoint  → DeterministicExecutor → MooKitClient (only write path)
```

- Publish tools return `ProposedAction` only; they do **not** call mooKIT write APIs.
- Confirm is always a **separate** HTTP request (`POST /v1/actions/{id}/confirm`).
- Executor payload comes from the stored DB row — never re-prompt the LLM at confirm time.
- Preview modal must reflect `ProposedAction.payload` exactly, not LLM paraphrase.

Violating this breaks the security model (injection red-team requires `unconfirmed_actions == 0`).

## Code layout

| Area | Path | Owns |
|------|------|------|
| Platform / integration | `app/api/*`, `app/mookit/*`, `app/store/*`, `app/core/{context,confirmation,executor,rate_limit}.py`, `app/files/*`, `app/workers/*`, `deploy/*` | HTTP, SSE, stores, gate, executor, RAG indexing |
| AI brain / domain | `app/core/{orchestrator,memory,reference_resolver,prompts,guardrails}.py`, `app/llm/*`, `app/tools/*`, `app/gen/*`, `app/preview/*`, `app/evals/*` | Orchestrator, tools, quiz pipeline, previews |
| Contracts (test seams) | `app/contracts/*` | Abstract interfaces; fakes in tests |
| Wiring | `app/core/wiring.py` | Binds production impls to `app.state` |

Shared contracts live in `app/contracts/`. Implement against interfaces; wire in `wiring.py`.

## Tenant isolation

Every storage key includes:

```
tenant_key = "{instance_id}:{course_id}"
```

Artifacts, RAG chunks, pending actions, transcripts, rate limits — all scoped by `tenant_key` (+ `user_id` for drafts). Never query without tenant filter.

Required request headers: `course`, `token`, `uid` (401 if missing).

## Tool tiers

| `risk_tier` | Behavior | Examples |
|-------------|----------|----------|
| `read` | Inline, mooKIT read or introspection | `whoami`, `resolve_taxonomy`, `my_permissions` |
| `draft` | Inline, writes artifact to PG only | `create_quiz`, `edit_quiz`, `draft_announcement`, `draft_lecture` |
| `publish` | Returns `ProposedAction`, stops LLM turn | `publish_assessment`, `send_announcement`, `publish_lecture` |

Tools declare `required_permission = ("resource", "action")`. Registry hides forbidden tools from the model.

## Extending

| Task | Touch |
|------|-------|
| New read/draft tool | Implement `Tool` in `app/tools/`, register in `wiring.py`, set permission, tests with contract fakes |
| New publish action | Publish tool → `ProposedAction` + preview builder in `app/preview/` + executor handler in `app/core/executor.py` + gate tests |
| New question type | Schema in `app/gen/quiz/schemas.py`, generator prompt, `to_mookit_payload()`, pipeline slot |
| New file format | Sandbox extractor in `app/files/`, MIME allowlist |
| New LLM provider | Implement `LLMProvider`, swap in wiring |

**Order:** contracts + fakes first → unit tests → wire to PG/Redis last.

## Product flows (quick reference)

All flows: **draft → preview → confirm → mooKIT write**.

1. **Quiz:** upload (`POST /v1/files`) → `create_quiz` → `edit_quiz` → `publish_assessment` → confirm
2. **Announcement:** `draft_announcement` → `send_announcement` → confirm (audience resolved server-side)
3. **Lecture:** upload → `draft_lecture` (taxonomy resolve) → `publish_lecture` → confirm

Narrative demo steps: [docs/demo-script.md](../../docs/demo-script.md).

## Development commands

```bash
# Offline tests (no infra, no API key)
uv run pytest -q -m "not live"
uv run ruff check app tests scripts && uv run mypy app

# Full stack
cp .env.example .env   # OPENAI__API_KEY, MOOKIT__BASE_URL, SECURITY__SECRET_KEY
cd deploy && sudo ./up.sh
# API: localhost:8000, UI: /ui, Swagger: /docs

# Live (funded key + IITK network for mooKIT)
uv run pytest -q -m live
MOOKIT_TOKEN=<jwt> uv run python scripts/probe_mookit.py
```

Use `docker compose` (v2), not legacy `docker-compose` v1.

## Common mistakes to avoid

- Calling `MooKitClient` write methods from a tool or the orchestrator loop
- Skipping `tenant_key` in new store queries
- Building preview from LLM text instead of `ProposedAction.payload`
- Allowing model-generated links/images in announcement bodies (sanitize in preview builders)
- Feeding publish results back into the LLM in the same turn
- Exposing tools the user lacks permission for

## Key docs

- [reference.md](reference.md) — architecture index, config, ops failures
- `docs/architecture-deep-dive.md` — full system design
- `docs/plan/09-mookit-api-reference.md` — LMS API shapes
- `README.md` — manual testing checklist
