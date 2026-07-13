# TripWeave

TripWeave reconstructs one shared trip from multiple travelers' camera rolls. Contributors upload photos after a trip. The system aligns time and location, groups media into days, stops, and moments, provides a review-by-exception workflow, and publishes an interactive map-and-timeline story.

This repository now contains the minimal local development foundation, the provider-neutral database foundation, and the first local owner workflow. It includes the web app, backend API, worker entry point, PostgreSQL/PostGIS container, local blob volume, checks, CI wiring, Alembic migrations, SQLAlchemy models, repository ports, PostgreSQL repository adapters, email/password authentication, server-side sessions, and local trip management. Upload endpoints, media processing, and cloud adapters are intentionally not implemented yet.

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

## Local Development

Prerequisites:

- Docker Desktop or a compatible Docker Engine with Compose
- Node.js 24 with Corepack
- Python 3.14
- uv 0.9.4 or newer

Start from a clean clone:

```sh
cp .env.example .env
corepack enable
corepack pnpm install --frozen-lockfile
cd services/backend && uv sync --frozen && cd ../..
make dev
```

Local service URLs:

- Web app: http://localhost:3000
- API liveness: http://localhost:8000/health/live
- API readiness: http://localhost:8000/health/ready
- API dependency status: http://localhost:8000/status
- PostgreSQL: localhost:5432

Common commands:

```sh
make dev
make down
make logs
make format
make lint
make typecheck
make test
make build
make check
```

The local database migrations enable PostGIS and create the first provider-neutral domain tables for users, sessions, trips, trip membership, invitations, uploads, media records, media assets, and processing jobs. The current product flow lets an owner register, sign in, create trips, edit trip settings, delete their own trips, and sign out.
