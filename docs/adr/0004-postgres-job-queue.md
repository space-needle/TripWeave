# ADR 0004: PostgreSQL Job Queue

## Status

Accepted

## Context

TripWeave needs durable processing for metadata extraction, alignment, grouping, derivative generation, publication, deletion, and repair tasks.

The local MVP should avoid adding an external queue service or cloud-specific managed queue before the core workflow is proven.

## Decision

TripWeave will use a durable PostgreSQL `processing_jobs` queue for the local MVP.

Jobs must be retryable or idempotent, persist state and attempts, and expose failure details for review and recovery.

## Consequences

The same local database can support product data and processing coordination during the MVP.

Future queue adapters may be considered only after the product workflow is proven, but domain and application modules should continue to depend on a provider-neutral job port.

Every database change to the queue schema requires an Alembic migration.
