#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.prod.yml}"
ENV_FILE="${TRIPWEAVE_ENV_FILE:-/etc/tripweave/tripweave.env}"
BACKUP_DIR="${TRIPWEAVE_BACKUP_DIR:-/var/backups/tripweave}"
STORE_ALIAS="${TRIPWEAVE_BACKUP_STORE_ALIAS:-db_backups}"
OBJECT_KEY="${1:?usage: deploy/scripts/restore.sh postgres/tripweave-YYYYMMDDTHHMMSSZ.dump}"
FILE_NAME="$(basename "$OBJECT_KEY")"
RESTORE_DB="${TRIPWEAVE_RESTORE_DB:-tripweave_restore}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing root-owned environment file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm \
  -v "${BACKUP_DIR}:/backups" \
  backup-uploader tripweave-backup download \
  --store-alias "$STORE_ALIAS" \
  --object-key "$OBJECT_KEY" \
  --file "/backups/${FILE_NAME}"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db dropdb \
  -U "${POSTGRES_USER:-tripweave}" --if-exists "$RESTORE_DB"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db createdb \
  -U "${POSTGRES_USER:-tripweave}" "$RESTORE_DB"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db pg_restore \
  -U "${POSTGRES_USER:-tripweave}" -d "$RESTORE_DB" < "${BACKUP_DIR}/${FILE_NAME}"

echo "Restored backup into database: $RESTORE_DB"
