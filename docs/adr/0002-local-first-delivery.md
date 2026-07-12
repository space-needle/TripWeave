# ADR 0002: Local-First Delivery

## Status

Accepted

## Context

TripWeave can deliver product value locally with a web app, backend, worker, database, local storage, and local tests. Introducing a cloud provider before the MVP would risk coupling the domain model to provider resources and slow product iteration.

## Decision

Stages 0 through 12 will complete the local MVP before any cloud SDK is introduced.

The local MVP uses:

- Next.js and TypeScript
- FastAPI
- Python worker
- PostgreSQL with PostGIS
- PostgreSQL `processing_jobs` queue
- local filesystem storage adapter
- Docker Compose for local execution when implementation begins

Stage 13 proves the provider contract. OCI is introduced only after that as one adapter and one deployment target.

## Consequences

Local end-to-end tests become the gate for cloud work.

Cloud SDKs, cloud infrastructure, and provider deployment resources are out of scope until the requested cloud-adapter stage.

Provider-neutral contracts must be designed early because the local adapter is the first implementation of the same interface future cloud adapters will use.
