#!/usr/bin/env bash
# Tail backend logs. Usage: ./logs.sh [api|worker|postgres|pgadmin|redis|all]
set -euo pipefail
svc="${1:-api}"
case "$svc" in
  api)      sudo docker logs -f deploy-api-1 ;;
  worker)   sudo docker logs -f deploy-worker-1 ;;
  postgres) sudo docker logs -f deploy-postgres-1 ;;
  pgadmin)  sudo docker logs -f deploy-pgadmin-1 ;;
  redis)    sudo docker logs -f deploy-redis-1 ;;
  all)
    sudo docker compose -f "$(dirname "$0")/docker-compose.yml" logs -f
    ;;
  *)
    echo "Usage: $0 [api|worker|postgres|pgadmin|redis|all]" >&2
    exit 1
    ;;
esac
