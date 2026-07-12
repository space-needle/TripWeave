# ADR 0001: Modular Monolith And Ports-And-Adapters

## Status

Accepted

## Context

TripWeave needs a coherent product workflow across uploads, metadata extraction, geospatial grouping, review, correction, and publication. Splitting this early across distributed services would add operational complexity before the product workflow is proven.

The product also needs strong cloud portability. Provider details must not leak into domain concepts or application use cases.

## Decision

TripWeave will use a modular monolith with ports-and-adapters boundaries.

Domain modules define product concepts and invariants. Application modules coordinate use cases through ports. Adapters implement persistence, storage, media processing, maps, and deployment-specific concerns.

Provider-specific code is allowed only under adapters, composition roots, deploy, and infra.

## Consequences

The local MVP can be developed and tested as one coherent system while preserving boundaries for future provider adapters.

The repository must enforce imports so domain and application modules do not depend on OCI, AWS, GCP, `boto3`, `google-cloud`, or other provider SDK packages.

Future extraction into services remains possible, but only after module boundaries and product behavior are proven.
