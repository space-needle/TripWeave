# Operations Runbook

## Start Local Stack

```sh
cp .env.example .env
make demo
```

Services:

- Web: http://localhost:3000
- API: http://localhost:8000
- API readiness: http://localhost:8000/health/ready
- Authenticated local ops: http://localhost:8000/ops/local-mvp

## Routine Checks

```sh
make smoke
make check
make e2e
```

`make smoke` validates local health, authenticated ops, and absence of cloud SDK lockfile markers.

## Worker

The worker polls PostgreSQL `processing_jobs` with row locking. Jobs are retried with backoff and safe error messages. If media is stuck:

1. Check `docker compose -f deploy/compose.local.yml logs worker`.
2. Check `/ops/local-mvp` for failed job counts.
3. Retry failed media from the owner media list when the UI exposes a retry.

## Backup And Restore Drill

```sh
make backup-restore-drill
```

The drill writes a temporary dump, restores it into `tripweave_restore_drill`, reads trip counts, then drops the temporary database.

## Storage

Local blobs live under the configured `TRIPWEAVE_BLOB_DIR`, split by logical store alias. Product records persist only `store_alias` and `object_key`.

Use `/ops/local-mvp` while signed in to inspect local storage usage. A soft-limit warning appears when usage reaches the configured trip-byte limit.

## Revocation

Revoking a share link immediately makes the public story unavailable. Previously copied sanitized derivatives may remain in local storage until a cleanup job is added.

## Incident Notes

- Do not run destructive database commands against the main local database unless the user explicitly asks.
- Do not add cloud SDKs or provider credentials during local MVP operations.
- Preserve failed jobs and audit rows for debugging unless a reset is explicitly requested.
