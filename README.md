# TripWeave

TripWeave reconstructs one shared trip from multiple travelers' camera rolls. Contributors upload photos after a trip. The system aligns time and location, groups media into days, stops, and moments, provides a review-by-exception workflow, and publishes an interactive map-and-timeline story.

This repository currently contains architecture documentation only. Application code, package files, Docker files, and infrastructure resources are intentionally out of scope for this stage.

## Architecture Direction

TripWeave is local-first and cloud-agnostic:

- Stages 0 through 12 deliver a complete local MVP.
- No cloud SDK is introduced before the local MVP passes end-to-end tests.
- Stage 13 proves the provider contract.
- OCI is added only after Stage 13 as one adapter and one deployment target.
- AWS and GCP remain possible future adapters.

The planned stack is:

- Next.js and TypeScript web application
- FastAPI backend
- Python worker
- PostgreSQL with PostGIS
- Durable PostgreSQL `processing_jobs` queue
- Local filesystem storage adapter for the local MVP
- Ports-and-adapters architecture inside a modular monolith
- Docker Compose for local execution
- Caddy and a single VM only at deployment time
- MapLibre with a configurable map-style URL

## Documentation Map

- `docs/architecture.md` defines the system shape and module boundaries.
- `docs/domain-model.md` defines the core product concepts and invariants.
- `docs/mvp-scope.md` defines the local MVP stages.
- `docs/security-and-privacy.md` defines ownership, deletion, publication, and secret-handling rules.
- `docs/cloud-portability-contract.md` defines provider-neutral storage contracts.
- `docs/roadmap.md` defines delivery order through local MVP, provider proof, and later deployment adapters.
- `docs/adr/` records architectural decisions.

## Non-Negotiable Boundaries

Domain and application modules must not import cloud provider SDKs or expose provider-specific storage terms. Provider-specific implementation belongs only in adapters, composition roots, deploy, and infra.

TripWeave stores logical `store_alias` and `object_key` values, never signed URLs or permanent provider URLs. Upload and download access is represented by provider-neutral `UploadGrant` and `DownloadGrant` contracts.

Original files and original metadata are immutable. Effective corrected values are stored separately, user corrections outrank automation, and published stories contain sanitized derivatives rather than originals.
