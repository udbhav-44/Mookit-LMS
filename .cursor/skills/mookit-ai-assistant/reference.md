# mooKIT AI Assistant — Reference

Read when you need deeper context beyond [SKILL.md](SKILL.md).

## Architecture docs map

| Doc | Contents |
|-----|----------|
| `docs/architecture-deep-dive.md` | Stack, topology, sequences, all subsystems |
| `docs/ai-architecture.md` | Orchestrator + quiz pipeline detail |
| `docs/demo-script.md` | Three demo flows (narrative) |
| `docs/production-setup.md` | Production runbook |
| `docs/plan/09-mookit-api-reference.md` | mooKIT REST API |
| `docs/eval-report.md` | Eval harness output |

## Contract interfaces (`app/contracts/`)

| Interface | Role |
|-----------|------|
| `RequestContext` | tenant, user, session, permissions, forwarded headers |
| `Tool` / `ToolResult` / `ProposedAction` | tool dispatch + publish proposals |
| `LLMProvider` / `LLMEvent` | provider-agnostic streaming |
| `MooKitClient` | LMS reads/writes |
| `SessionStore` | transcript messages |
| `ArtifactRegistry` | versioned drafts |
| `PreviewRender` | confirm modal payload |

## Registered tools

`echo` · `whoami` · `resolve_taxonomy` · `my_permissions` · `create_quiz` · `edit_quiz` ·
`publish_assessment` · `draft_announcement` · `send_announcement` · `draft_lecture` · `publish_lecture`

## Executor dispatch

| action | mooKIT sequence |
|--------|-----------------|
| `publish_assessment` | POST assessment status=0 → section → questions → PUT publish status=1 |
| `send_announcement` | resolve audience → POST announcement |
| `publish_lecture` | POST lecture → upload file if needed → attach resource |

## Confirmation gate

- `content_hash = sha256(json.dumps(payload, sort_keys=True))`
- Token TTL: `SECURITY__CONFIRM_TOKEN_TTL_SECONDS` (default 3600)
- Confirm re-checks permissions (handles revocation between propose and confirm)
- Hash mismatch or consumed token → 404 (vague)
- Editing a draft after proposal voids the token (must re-confirm)

## Config (nested env `FOO__BAR`)

Key vars in `.env.example`:

- `OPENAI__API_KEY` — chat, quiz gen, embeddings, moderation
- `MOOKIT__BASE_URL` — LMS REST base
- `SECURITY__SECRET_KEY`, `SECURITY__SERVICE_API_KEY`, `SECURITY__ALLOWED_ORIGINS`
- `LIMITS__RATE_LIMIT_RPM`
- `AUTO_CREATE_TABLES` — set `false` in production; use Alembic

## Stack processes (Docker)

| Process | Role |
|---------|------|
| `deploy-api-1` | HTTP + SSE, enqueue jobs |
| `deploy-worker-1` | extract → chunk → embed |
| `deploy-postgres-1` | artifacts, RAG vectors, pending_actions |
| `deploy-redis-1` | transcripts, cache, ARQ broker, rate limits |

Shared volume: `/tmp/mookit_uploads` on api + worker.

## Common ops failures

| Symptom | Likely cause |
|---------|--------------|
| 401 on chat | Missing `course`/`token`/`uid` headers |
| 403 on mooKIT reads | JWT ok but wrong `course` header |
| 404 on confirm | Expired/consumed token, hash mismatch, cross-tenant |
| Quiz empty / no citations | File not indexed yet — check worker logs |
| `ContainerConfig` on compose | Using legacy `docker-compose` v1 — use `docker compose` |

## Test markers

- Default: `pytest -m "not live"` — fakes, no OpenAI/mooKIT
- Live: `pytest -m live` — requires API key and network
- Injection red-team: `app/evals/injection_redteam.py`
- Offline flow tests: `tests/test_cp4_flows.py`

## SSE event types (chat)

`tool_started` · `artifact_updated` · `assistant_delta` · `pending_confirmation` · `done`

Parser must handle CRLF (`sample-ui/index.html` reference client).
