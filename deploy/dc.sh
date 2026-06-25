#!/usr/bin/env bash
# Compose wrapper that always loads ../.env from deploy/.
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

exec sudo "${COMPOSE[@]}" "$@"
