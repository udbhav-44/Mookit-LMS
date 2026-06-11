#!/usr/bin/env bash
# Start the full stack. Requires Docker Compose v2 (`docker compose`), not legacy docker-compose v1.
set -euo pipefail
cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  echo "ERROR: legacy docker-compose v1 is incompatible with Docker 29+." >&2
  echo "Install Compose v2: sudo apt-get install -y docker-compose-v2" >&2
  exit 1
else
  echo "ERROR: docker compose not found." >&2
  exit 1
fi

ENV_FILE="../.env"
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE+=(--env-file "$ENV_FILE")
fi

# Remove stale containers left by broken v1 recreate (avoids name/network conflicts).
sudo docker rm -f \
  deploy_api_1 deploy_worker_1 deploy_postgres_1 deploy_redis_1 deploy_pgadmin_1 \
  5c29cb3e4870_deploy_redis_1 f3a30a54a606_deploy_postgres_1 \
  2>/dev/null || true

sudo "${COMPOSE[@]}" down --remove-orphans 2>/dev/null || true
sudo "${COMPOSE[@]}" up -d --build "$@"

HOST_IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "Stack up. Sample UI: http://${HOST_IP}:8000/ui"
echo "pgAdmin:           http://${HOST_IP}:5050  (login admin@local.dev / admin)"
echo "                   Server 'mooKIT LMS' is pre-configured (postgres/postgres)"
echo "Health:            http://localhost:8000/health/live"
