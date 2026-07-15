#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.local.yml}"
SOURCE_DB="${POSTGRES_DB:-tripweave}"
RESTORE_DB="${TRIPWEAVE_RESTORE_DRILL_DB:-tripweave_restore_drill}"
USER_NAME="${POSTGRES_USER:-tripweave}"
BACKUP_PATH="/tmp/tripweave_restore_drill.dump"

docker compose -f "$COMPOSE_FILE" exec -T db pg_dump -U "$USER_NAME" -Fc "$SOURCE_DB" > "$BACKUP_PATH"
docker compose -f "$COMPOSE_FILE" exec -T db dropdb -U "$USER_NAME" --if-exists "$RESTORE_DB"
docker compose -f "$COMPOSE_FILE" exec -T db createdb -U "$USER_NAME" "$RESTORE_DB"
docker compose -f "$COMPOSE_FILE" exec -T db pg_restore -U "$USER_NAME" -d "$RESTORE_DB" < "$BACKUP_PATH"
docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$USER_NAME" -d "$RESTORE_DB" -c "select count(*) as trips from trips;"
docker compose -f "$COMPOSE_FILE" exec -T db dropdb -U "$USER_NAME" --if-exists "$RESTORE_DB"
rm -f "$BACKUP_PATH"
