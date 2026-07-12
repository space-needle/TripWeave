# Roadmap

TripWeave delivery is intentionally local-first. The product must prove its core workflow locally before cloud adapters or deployment targets are added.

## Current Stage

Stage 0: Documentation Baseline.

This stage creates the architecture documentation and ADRs only. It does not add application code, package files, Docker files, or infrastructure resources.

## Local MVP

Stages 1 through 12 build the complete local MVP:

- local service skeleton
- database foundation with Alembic migrations
- local filesystem storage adapter
- upload flow
- metadata extraction
- PostgreSQL processing job queue
- timestamp and location alignment
- grouping into days, stops, and moments
- review-by-exception workflow
- story drafting
- versioned sanitized publication
- local end-to-end tests

The local MVP must pass end-to-end tests before any cloud SDK is introduced.

## Provider Proof

Stage 13 proves the provider contract. The goal is to validate that storage behavior is represented by `BlobRef`, `UploadGrant`, `DownloadGrant`, `StorageCapabilities`, logical store aliases, and provider contract tests.

## Cloud Adapters

After Stage 13, OCI may be added as one adapter and one deployment target. OCI must not become a core product assumption.

AWS and GCP remain possible future adapters. Their viability depends on preserving provider-neutral domain and application modules.

## Deployment Direction

Deployment is introduced after the local MVP. The intended first deployment shape is Caddy and a single VM. Multi-provider deployment may be added later through isolated deploy and infra modules.
