# Production Setup

What you must provide + the exact steps to run the mooKIT AI Assistant in production. The code has no
fakes in the runtime path: real OpenAI, real pgvector embeddings RAG, real OpenAI Moderation guardrails,
real mooKIT writes through the deterministic confirmation executor.

## 1. Provide credentials / access
- **OpenAI**: a funded key → `OPENAI__API_KEY` (or flat `OPENAI_API_KEY`). Used for chat, quiz
  generation, embeddings (`text-embedding-3-small`), and Moderation.
- **mooKIT**: auth is pass-through — the mooKIT frontend forwards `course` / `token` / `uid` per
  request. URL scheme is `https://test.mookit.in/v2/api/{course}/{endpoint}` →
  `MOOKIT__BASE_URL=https://test.mookit.in/v2/api` (course is appended automatically). For your own
  probes, supply a full JWT (`MOOKIT_TOKEN`); the token in `docs/details.md` is truncated.
- **Network**: the deploy host must reach the mooKIT instance (IITK network/VPN).
- **Secrets**: set a real `SECURITY__SECRET_KEY` (≥32 chars). Optionally set
  `SECURITY__SERVICE_API_KEY` (shared secret the frontend sends as `x-service-key`) and
  `SECURITY__ALLOWED_ORIGINS` (CORS allowlist) to lock the trust boundary.

## 2. Stand up infrastructure
`docker compose -f deploy/docker-compose.yml up --build` brings up **api + worker + postgres + redis**.
Postgres must have the `vector` extension (the migration / startup creates it; the role needs
permission to `CREATE EXTENSION`).

### Network exposure policy (critical)
- Expose only the UI/API entrypoint and SSH at the host perimeter.
- `postgres` and `redis` are internal-only in Compose (no host port publishing).
- Redis now requires authentication (`REDIS_PASSWORD`) and clients use
  `REDIS__URL=redis://:${REDIS_PASSWORD}@redis:6379/0`.
- `pgadmin` is opt-in via profile and bound to localhost by default:
  `docker compose --profile ops up -d pgadmin`.

## 3. Database migrations (production)
Set `AUTO_CREATE_TABLES=false` in prod and run Alembic:
```bash
alembic upgrade head        # creates the vector extension + all tables (baseline 0001_initial)
```
For new schema changes: `alembic revision --autogenerate -m "..."` then `alembic upgrade head`.
(Out-of-the-box/dev keeps `AUTO_CREATE_TABLES=true`, which creates tables on startup.)

## 4. RAG backend
`RAG_BACKEND=pgvector` (default) uses OpenAI embeddings + pgvector cosine search in Postgres. The worker
embeds + indexes uploaded documents (`doc_chunks` table); the quiz pipeline retrieves grounded spans.
`RAG_BACKEND=keyword` falls back to Redis term-overlap (no embeddings) if needed.

## 5. Reverse proxy / TLS (SSE-safe)
Terminate TLS at nginx/ingress. For the `/v1/chat` SSE stream: **disable proxy buffering** and set the
idle/read timeout **above** the 15s heartbeat (e.g. nginx `proxy_buffering off; proxy_read_timeout
300s;`). Route only the mooKIT frontend to the service (network policy + `SECURITY__SERVICE_API_KEY`).

## 6. Verify before go-live
```bash
MOOKIT_TOKEN=<jwt> python scripts/probe_mookit.py     # live reads (users_me, permissions, taxonomy)
pytest -q -m live                                     # one real streamed OpenAI turn
# Should fail from outside the host after hardening:
#   nc -vz <host> 6379   # closed
#   nc -vz <host> 5432   # closed
# then exercise each flow end-to-end via /ui or the API:
#   quiz from a PDF  ·  announcement  ·  lecture (with a real video upload)
```

## 7. Operational hardening (recommended)
- **File sandbox**: `app/files/sandbox.py` uses a subprocess + `setrlimit` (CPU/mem) but network
  isolation is best-effort — run the **worker** in a network-restricted container (egress denied) and add
  an AV scan hook for true isolation.
- **Observability**: set `LANGFUSE_*` / `OTEL_EXPORTER_OTLP_ENDPOINT` to enable tracing + per-tenant
  token/cost dashboards.
- **Instance registry**: populate the `instance_registry` table to map `instanceId → mooKIT base URL`
  for multi-instance support.
- **Scaling**: stateless API pods behind the Redis pub/sub backplane (no sticky sessions); scale the ARQ
  worker independently. CPU only — no GPU.
- **Backups**: Postgres backups; rotate the OpenAI key.

## Environment variables (summary)
See `.env.example`. Key ones: `OPENAI__API_KEY`, `MOOKIT__BASE_URL`, `DB__URL`, `REDIS__URL`,
`SECURITY__SECRET_KEY`, `SECURITY__SERVICE_API_KEY`, `SECURITY__ALLOWED_ORIGINS`, `RAG_BACKEND`,
`AUTO_CREATE_TABLES`.
