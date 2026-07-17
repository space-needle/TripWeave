#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.prod.yml}"
ENV_FILE="${TRIPWEAVE_ENV_FILE:-/etc/tripweave/tripweave.env}"
PUBLIC_BASE="${TRIPWEAVE_HEALTH_BASE_URL:-}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing root-owned environment file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d db

echo "Waiting for database health..."
for _ in $(seq 1 60); do
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db pg_isready \
    -U "${POSTGRES_USER:-tripweave}" -d "${POSTGRES_DB:-tripweave}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm api alembic upgrade head
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api worker web caddy

if [ -n "$PUBLIC_BASE" ]; then
  echo "Waiting for public API readiness at $PUBLIC_BASE/api/health/ready..."
  for _ in $(seq 1 60); do
    if curl -fsS "$PUBLIC_BASE/api/health/ready" >/dev/null; then
      echo "Deployment healthy."
      exit 0
    fi
    sleep 5
  done
  echo "Deployment did not become healthy before timeout." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
