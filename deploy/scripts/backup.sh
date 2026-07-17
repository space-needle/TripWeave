#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.prod.yml}"
ENV_FILE="${TRIPWEAVE_ENV_FILE:-/etc/tripweave/tripweave.env}"
BACKUP_DIR="${TRIPWEAVE_BACKUP_DIR:-/var/backups/tripweave}"
STORE_ALIAS="${TRIPWEAVE_BACKUP_STORE_ALIAS:-db_backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE_NAME="tripweave-${STAMP}.dump"
OBJECT_KEY="postgres/${FILE_NAME}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing root-owned environment file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db pg_dump \
  -U "${POSTGRES_USER:-tripweave}" -Fc "${POSTGRES_DB:-tripweave}" > "${BACKUP_DIR}/${FILE_NAME}"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm \
  -v "${BACKUP_DIR}:/backups:ro" \
  backup-uploader tripweave-backup upload \
  --file "/backups/${FILE_NAME}" \
  --store-alias "$STORE_ALIAS" \
  --object-key "$OBJECT_KEY"

echo "Uploaded backup object: ${STORE_ALIAS}/${OBJECT_KEY}"
