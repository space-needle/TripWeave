# ADR 0006: Provider-Specific Infrastructure Isolation

## Status

Accepted

## Context

TripWeave may eventually deploy to OCI and may later support AWS or GCP. If infrastructure concepts leak into the core product, future adapters become expensive and risky.

Earlier OCI-first plans, if reintroduced, are superseded by this ADR. OCI is not the product architecture; it is a possible future adapter and deployment target after the provider contract is proven.

## Decision

Provider-specific infrastructure code, SDK imports, runtime identity setup, and deployment configuration are isolated under adapters, composition roots, deploy, and infra.

Domain and application modules must not import cloud SDKs and must not expose provider-specific terms in public types.

No destructive infrastructure command, including `terraform apply` or an equivalent operation, may be run without explicit user approval.

## Consequences

The local MVP remains independent of cloud providers.

OCI can be added later without blocking future AWS or GCP adapters.

Provider-specific docs and configuration must map logical aliases and provider-neutral contracts to concrete provider resources without changing core product modules.
