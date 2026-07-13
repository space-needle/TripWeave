# Worker State Machine

TripWeave uses PostgreSQL `processing_jobs` as the durable local queue. Workers claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers can run without claiming the same row.

## Job States

- `pending`: eligible when `run_after` is due and `attempts < max_attempts`.
- `running`: claimed transactionally by one worker. The worker sets `locked_at`, `locked_by`, increments `attempts`, and clears prior error fields.
- `succeeded`: the job completed and released its lock.
- `failed`: the job reached a final, safe failure. For media ingest, the media item is marked `failed`.

Running jobs with `locked_at` older than `TRIPWEAVE_WORKER_LOCK_TIMEOUT_SECONDS` are eligible for recovery and can be claimed again.

## Failure And Retry

Retryable failures return to `pending` with exponential backoff and jitter. Final media validation failures, such as invalid signatures, unsupported image types, corrupt images, and oversized decoded images, mark only the affected media item as failed. Other media in the trip continue processing independently.

Workers record structured `error_code` values and safe `error_message` text. Logs include IDs such as job and worker IDs, not private EXIF metadata, object tokens, or user-provided file contents.

## INGEST_MEDIA

`INGEST_MEDIA` jobs are idempotent for a single media item:

1. Open the immutable original through `BlobStore`.
2. Verify the image signature independently from the filename and declared MIME type.
3. Enforce original-byte, decoded-pixel, and decoded-memory limits.
4. Calculate SHA-256.
5. Decode JPEG and HEIC when local codec support is available.
6. Extract safe EXIF/XMP metadata, dimensions, orientation, capture time, UTC offset, GPS presence, and camera hints.
7. Normalize orientation and generate WebP thumbnail and display derivatives.
8. Store derivatives under logical store aliases and deterministic object keys.
9. Upsert `media_assets` for `thumbnail` and `display`.
10. Mark the media item `ready`.

Re-running the same job rewrites the same derivative object keys and updates existing asset rows instead of creating duplicates.
