# Cloud Adapter Guide

TripWeave has not added OCI, AWS, or GCP SDKs yet. This guide defines the proof that a future cloud adapter can be added without changing domain logic, application use cases, database semantics, or public API contracts.

## Stage 13 Contract

Before adding a provider SDK:

- Domain and application modules must continue to depend only on provider-neutral ports.
- API schemas must not expose provider terms such as bucket, namespace, PAR, S3, GCS, OCI, presigned URL, or signed URL.
- Database records must persist logical `store_alias` and `object_key`, never provider resource names or durable URLs.
- Published manifests must contain asset IDs and `BlobRef` objects, never local paths or provider URLs.
- Every adapter must pass the reusable BlobStore contract tests unchanged.
- Provider-specific tests must be skipped unless explicit provider environment variables are present.
- Multi-architecture container builds must pass for `linux/amd64` and `linux/arm64`.

## Composition Root

Provider selection happens only in the storage composition root:

- `TRIPWEAVE_STORAGE_ADAPTER=local` selects the local filesystem adapter.
- Future values such as `oci`, `s3`, or `gcs` may be added only inside adapter/composition-root code.
- Provider-specific environment namespaces must be ignored unless their adapter is selected.
- Domain, application, API schemas, migrations, and publication manifests must not branch on provider names.

The current local MVP intentionally supports only `local`.

## BlobStore Contract

All storage adapters implement the same port:

- `create_upload_grant`
- `create_download_grant`
- `stat`
- `open_reader`
- `put`
- `delete`
- `exists`
- `capabilities`

The shared contract suite lives in `services/backend/tests/blob_store_contract.py`. It is run against:

- `FakeInMemoryBlobStore` for fast provider-neutral tests.
- `LocalBlobStore` for local filesystem behavior.

Future provider tests should import the same contract suite and skip unless explicit environment variables are present, for example:

```python
pytestmark = pytest.mark.skipif(
    not os.environ.get("TRIPWEAVE_PROVIDER_TESTS"),
    reason="provider integration tests require explicit opt-in",
)
```

Provider tests must never run as part of ordinary `make check` unless they use fake/local adapters.

## Capabilities

Adapters describe behavior with provider-neutral flags:

- `supports_api_proxy_upload`
- `supports_single_put_upload`
- `supports_multipart_upload`
- `supports_resumable_upload`
- `supports_ranged_read`
- `supports_direct_upload`
- `supports_direct_download`
- `supports_server_side_copy`
- `supports_conditional_write`
- `supports_checksum_verification`
- `supports_temporary_grants`
- `maximum_single_upload_bytes`
- `recommended_part_size_bytes`

Application services may branch on these flags, but not on provider names. If a capability is absent, use the available fallback:

- Uploads fall back to `api_proxy`.
- Publication copies fall back to `open_reader` plus `put` when server-side copy is absent.
- Reads fall back to full-object reads when ranged reads are absent.

## Adapter Authoring Rules

A new adapter must:

1. Preserve object keys exactly.
2. Map logical aliases to provider-specific resources internally.
3. Return provider-neutral `UploadGrant` and `DownloadGrant` shapes.
4. Treat grant URLs as temporary and never persist them.
5. Verify checksums when the provider exposes enough information.
6. Reject path traversal, unknown aliases, absolute object keys, NUL bytes, and equivalent escape attempts.
7. Keep provider SDK imports under adapters, composition roots, deploy, or infra.
8. Pass the shared BlobStore contract suite without modifying it.
9. Add provider integration tests that are skipped unless opt-in environment variables are present.
10. Document required runtime identity and least-privilege permissions in provider-specific docs.

## API And Database Guardrails

Architecture tests enforce:

- Domain/application do not import adapters or cloud SDKs.
- Cloud SDK imports are confined to adapters or composition roots.
- API schemas do not contain provider-specific storage fields.
- Alembic migrations do not introduce provider-specific storage semantics.
- Publication manifest builders do not emit durable URL fields.
- Lock files contain no cloud SDK dependency markers.

If one of these tests fails while adding an adapter, the adapter is leaking provider semantics into the product model.

## Migration Design

Cross-provider migration is not implemented yet. The design is:

1. Run a dry-run inventory of every persisted `BlobRef` grouped by `store_alias`.
2. For each object, verify the source adapter can read metadata and content.
3. Copy to the destination adapter using the identical `object_key`.
4. Verify `size_bytes` and checksum after each copy.
5. Record per-object migration status outside core product records.
6. On dry-run, report planned copies, missing objects, checksum mismatches, and projected bytes without writing destination objects.
7. On execution, write destination objects, verify checksums, and produce a rollback report.
8. Switch logical alias configuration only after every required object verifies.

The migration must not rewrite trip, media, asset, publication, or manifest records merely because the provider changes. Only checksums or explicit repair metadata may change when integrity problems are found.

## Multi-Architecture Build Proof

Run:

```sh
make build-multiarch
```

The script uses Docker Buildx with `--platform linux/amd64,linux/arm64` and `--output=type=cacheonly` for the PostGIS, backend, and web images. It proves the images build for both runtime architectures without pushing provider-specific artifacts.

## Current Result

The repository currently proves the storage contract with fake and local adapters only. No OCI, AWS, or GCP SDK dependency is present.
