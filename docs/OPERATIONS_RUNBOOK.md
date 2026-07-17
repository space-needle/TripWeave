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
make backup-restore-drill
```

`make smoke` validates local health, authenticated ops, storage aliases, warning flags, and absence of cloud SDK lockfile markers. Treat its JSON output as the first triage summary before sharing a build with external testers.

Review these fields in the smoke output:

- `counts`: users, trips, members, and active share links.
- `jobStates`, `mediaStates`, `uploadStates`, `shareLinkStates`: aggregate state counts.
- `worker.ok` and `warnings.workerStale`: worker heartbeat health.
- `storage.totalBytes`, `storage.aliases`: local blob usage by logical store.
- `warnings.usingDefaultStorageSigningSecret`: must be `false` outside local-only testing.
- `recentFailureCount`: non-zero means inspect `/ops/local-mvp` before inviting testers.

## Pre-Tester Configuration

Before running a build that anyone else will access:

1. Set `TRIPWEAVE_STORAGE_SIGNING_SECRET` to a random value with at least 16 characters.
2. Set `TRIPWEAVE_ALLOWED_WEB_ORIGINS` to the actual web origin.
3. Set `TRIPWEAVE_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_API_BASE_URL` to the externally reachable API URL.
4. Set `TRIPWEAVE_ENV=production` only when HTTPS is available; it enables secure cookies.
5. Keep `TRIPWEAVE_STORAGE_STORE_ALIASES=media_private,story_published`.
6. Run `make smoke` and confirm no warning blocks the tester flow.

## Worker

The worker polls PostgreSQL `processing_jobs` with row locking. Jobs are retried with backoff and safe error messages. If media is stuck:

1. Check `docker compose -f deploy/compose.local.yml logs worker`.
2. Check `/ops/local-mvp` for failed job counts and `recentFailures`.
3. Retry failed media from the owner media list when the UI exposes a retry.

## Backup And Restore Drill

```sh
make backup-restore-drill
```

The drill writes a temporary dump, restores it into `tripweave_restore_drill`, reads trip counts, then drops the temporary database.

## Storage

Local blobs live under the configured `TRIPWEAVE_BLOB_DIR`, split by logical store alias. Product records persist only `store_alias` and `object_key`.

Use `/ops/local-mvp` while signed in to inspect local storage usage. A soft-limit warning appears when usage reaches the configured trip-byte limit. `media_private` contains originals and private derivatives; `story_published` contains sanitized published story assets.

If `storage.totalBytes` grows unexpectedly:

1. Confirm uploads are intentional and not repeated retries.
2. Check `uploadStates` for stuck registrations or transfers.
3. Check `mediaStates` and `recentFailures` for processing loops.
4. Do not manually delete blob files unless the matching database records are part of an explicit repair plan.

## Revocation

Revoking a share link immediately makes the public story unavailable. Previously copied sanitized derivatives may remain in local storage until a cleanup job is added.

## Incident Notes

- Do not run destructive database commands against the main local database unless the user explicitly asks.
- Do not add cloud SDKs or provider credentials during local MVP operations.
- Preserve failed jobs and audit rows for debugging unless a reset is explicitly requested.
- Use `x-request-id` from API responses to connect browser reports to structured backend logs.
