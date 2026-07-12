# MVP Scope

The MVP is delivered local-first in Stages 0 through 12. It must pass local end-to-end tests before any cloud SDK or provider adapter is added.

## MVP Goal

Given photos from multiple travelers after a trip, TripWeave should reconstruct a shared trip, surface only the exceptions that need review, and publish an interactive map-and-timeline story using sanitized derivatives.

## In Scope For Local MVP

- Local development and test workflow
- Next.js and TypeScript web app
- FastAPI backend
- Python worker
- PostgreSQL with PostGIS
- Durable PostgreSQL `processing_jobs` queue
- Local filesystem storage adapter
- Contributor uploads
- Metadata extraction
- Timestamp and location alignment
- Day, stop, and moment grouping
- Review-by-exception workflow
- User corrections
- Sanitized derivative generation
- Versioned story publication
- MapLibre story map with configurable map-style URL
- Authorization tests for every authorization rule
- Alembic migrations for every database change

## Out Of Scope Before Local MVP Completion

- OCI SDKs or deployment resources
- AWS SDKs or deployment resources
- GCP SDKs or deployment resources
- Cloud object storage
- Cloud identity integrations
- Terraform or equivalent infrastructure apply
- Multi-VM or managed orchestration deployments
- Persisting signed URLs or permanent provider URLs

## Stages

### Stage 0: Documentation Baseline

Create architecture, domain, security, portability, roadmap, and ADR documentation. No application code.

### Stage 1: Local Skeleton

Introduce the minimal repository structure, local development commands, and empty service boundaries for the web app, backend, worker, and database migrations.

### Stage 2: Database Foundation

Add PostgreSQL schema and Alembic migrations for trips, contributors, media assets, original metadata, corrections, automated results, and processing jobs.

### Stage 3: Local Storage Adapter

Implement provider-neutral storage ports and the local filesystem adapter using logical store aliases and object keys.

### Stage 4: Upload Flow

Enable contributor upload into local storage through `UploadGrant` semantics and record immutable media assets.

### Stage 5: Metadata Extraction

Extract original metadata without mutating originals. Store extraction source, confidence where applicable, and algorithm version for automated results.

### Stage 6: Processing Queue

Implement the durable PostgreSQL `processing_jobs` worker loop with retries, idempotency, and observable failure states.

### Stage 7: Time And Location Alignment

Align timestamps, timezone clues, and GPS data. Preserve originals and store effective values separately.

### Stage 8: Grouping

Group media into days, stops, and moments. Store automated grouping output with source, confidence, and algorithm version.

### Stage 9: Review By Exception

Build review screens for low-confidence, conflicting, missing, or privacy-sensitive results. User corrections outrank automation.

### Stage 10: Story Drafting

Build a private interactive map-and-timeline draft using MapLibre and configurable map-style URL.

### Stage 11: Publication

Create versioned publication snapshots with sanitized derivatives only. Originals remain private.

### Stage 12: Local End-To-End MVP

Complete local end-to-end tests covering upload, processing, correction, authorization, deletion control, and publication.

### Stage 13: Provider Contract Proof

Run provider contract tests against the local adapter and at least one non-production test adapter or harness without introducing provider assumptions into domain or application modules.

### Later: OCI Adapter And Single-VM Deployment

Add OCI only as one storage adapter and one deployment target. Keep AWS and GCP viable by preserving the provider-neutral contract.
