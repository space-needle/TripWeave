# Architecture

TripWeave is a local-first, cloud-agnostic modular monolith. The local MVP must run end to end before any cloud SDK or provider deployment target is introduced.

## System Shape

The target architecture contains:

- Next.js and TypeScript web application
- FastAPI backend
- Python worker
- PostgreSQL with PostGIS
- Durable PostgreSQL `processing_jobs` queue
- Local filesystem storage adapter for the local MVP
- Ports-and-adapters boundaries inside a modular monolith
- Docker Compose for local execution
- Caddy and a single VM only at deployment time
- MapLibre with a configurable map-style URL

The monolith is modular in source structure and runtime behavior. The backend and worker share domain and application modules, while adapters provide persistence, storage, media processing, map style configuration, and deployment-specific wiring.

## Delivery Order

1. Stages 0 through 12 complete the local MVP.
2. No cloud SDK is introduced before the local MVP passes end-to-end tests.
3. Stage 13 proves the provider contract against provider-neutral tests.
4. OCI is added only after Stage 13 as one adapter and one deployment target.
5. AWS and GCP remain possible future adapters.

## Ports And Adapters

Domain modules hold business concepts and invariants. Application modules coordinate use cases and depend on ports. Adapters implement those ports.

Provider-specific code is permitted only in:

- storage adapters
- composition roots
- deployment scripts and configuration
- infrastructure definitions

Provider-specific code is prohibited in:

- domain modules
- application modules
- public domain or application types
- database schema names that would make one provider the product model

## Runtime Components

The Next.js app provides upload, review, correction, and published-story experiences. The FastAPI backend exposes authenticated API endpoints and coordinates application services. The Python worker processes durable jobs from PostgreSQL.

PostgreSQL is the source of truth for trips, contributors, media records, metadata, corrections, computed grouping, publication versions, authorization state, and processing jobs. PostGIS stores and queries geospatial facts used for alignment, clustering, stops, map views, and story geometry.

The local filesystem is the first storage adapter. It implements the same storage port that future cloud adapters must implement.

## Data And Processing Flow

1. A trip owner creates a trip and invites contributors.
2. Contributors upload media through provider-neutral `UploadGrant` contracts.
3. The system records immutable originals with logical `store_alias` and `object_key`.
4. Metadata extraction stores original metadata separately from corrections.
5. Worker jobs align timestamps and locations, group media into days, stops, and moments, and emit automated results with source, confidence, and algorithm version.
6. Review screens surface exceptions and low-confidence results.
7. User corrections create effective values that outrank automation.
8. Publication creates versioned sanitized derivatives and story data.
9. Published stories serve derivatives only, never originals.

## Storage Boundary

Storage references use:

- `store_alias`: logical store name such as `originals`, `derivatives`, or `exports`
- `object_key`: stable logical object path within that store
- checksum and size metadata for integrity

TripWeave does not persist signed URLs or permanent provider URLs. Access is granted through `UploadGrant` and `DownloadGrant`, which are provider-neutral contracts.

## Database And Jobs

Every database change requires an Alembic migration. The durable queue lives in PostgreSQL as `processing_jobs` so local development, tests, and deployment use the same job semantics.

Jobs must be idempotent or safely retryable. Job records should capture state, attempts, error details, and enough input references to resume without relying on in-memory state.

## Deployment Boundary

Local execution uses Docker Compose once implementation begins. Deployment is introduced later and uses Caddy plus a single VM only after the local MVP is proven. Provider-specific deployment assets remain isolated under deploy and infra.

Runtime container images must support `linux/amd64` and `linux/arm64`.

## Map Boundary

The map UI uses MapLibre. The map-style URL is configuration, not a hard-coded provider dependency. Map rendering must not leak private original media locations beyond authorized views and sanitized publication data.
