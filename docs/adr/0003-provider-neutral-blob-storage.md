# ADR 0003: Provider-Neutral Blob Storage

## Status

Accepted

## Context

TripWeave stores originals, derivatives, imports, and exports. The product must support local filesystem storage first and later allow OCI, AWS, or GCP without changing domain or application modules.

Persisting provider URLs, bucket concepts, namespaces, or signed access material would make migration harder and expose private implementation details.

## Decision

TripWeave will persist provider-neutral `BlobRef` records containing logical `store_alias` and `object_key` values plus integrity metadata.

Temporary access will use provider-neutral `UploadGrant` and `DownloadGrant` contracts. Adapter behavior will be described through `StorageCapabilities`.

Provider-specific storage details are confined to storage adapters, composition roots, deploy, and infra.

## Consequences

Domain and application modules do not know whether storage is local, OCI, AWS, GCP, or another provider.

Application records remain portable across providers as long as object keys are preserved and checksums verify.

Provider contract tests are required for every storage adapter.
