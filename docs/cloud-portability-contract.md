# Cloud Portability Contract

TripWeave storage is provider-neutral. Local filesystem storage is the first implementation, and future OCI, AWS, or GCP support must implement the same contract without changing domain or application modules.

## BlobRef

`BlobRef` is the persisted reference to stored content.

Fields:

- `store_alias`: logical store name controlled by TripWeave configuration
- `object_key`: stable object key within the logical store
- `checksum_algorithm`: checksum algorithm used for integrity verification
- `checksum`: checksum value
- `size_bytes`: content size when known
- `content_type`: media type when known

`BlobRef` must not contain signed URLs, permanent provider URLs, bucket names, namespaces, account names, regions, credentials, or provider resource identifiers.

## UploadGrant

`UploadGrant` authorizes a client or service to upload one object without exposing provider-specific concepts to domain or application modules.

Fields:

- `blob_ref`: the expected logical destination, including `store_alias` and `object_key`
- `method`: upload method such as direct local write, HTTP PUT, or multipart protocol
- `url`: temporary grant endpoint when the adapter supports URL-based upload
- `headers`: provider-neutral required request headers
- `expires_at`: expiration timestamp
- `max_size_bytes`: maximum accepted size
- `content_type`: expected content type when constrained

The persisted record is the resulting `BlobRef`, not the grant URL.

## DownloadGrant

`DownloadGrant` authorizes temporary read access to a stored object or derivative.

Fields:

- `blob_ref`: logical object being read
- `method`: download method such as local stream or HTTP GET
- `url`: temporary grant endpoint when the adapter supports URL-based download
- `headers`: provider-neutral required request headers
- `expires_at`: expiration timestamp
- `content_type`: content type when known
- `size_bytes`: content size when known

The system must not persist `DownloadGrant.url` as a permanent reference.

## StorageCapabilities

`StorageCapabilities` describes adapter behavior without revealing provider branding.

Fields:

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

Application services may branch on capabilities, but must not branch on provider names.
When a capability is absent, the application must use a supported fallback such as
`api_proxy` upload or stream-copy through `open_reader` and `put`.

## Logical Store Aliases

Logical store aliases map product intent to adapter configuration. Examples:

- `originals`
- `derivatives`
- `exports`
- `imports`

Aliases are stable product configuration, not provider resource names. A provider adapter maps aliases to local directories, buckets, containers, or other provider-specific locations internally.

Object keys must remain stable across providers. They should encode product-owned structure, such as trip id, contributor id, media id, derivative kind, and version, without embedding provider names or signed access material.

## Provider Contract Tests

Every storage adapter must pass the same provider contract tests:

- create upload grant for a logical store alias and object key
- upload content and verify size and checksum
- reject writes that violate content type or size limits when configured
- create download grant and read back exact bytes
- verify missing object behavior
- verify overwrite or conditional-write semantics
- verify delete behavior
- verify copy behavior only when the adapter declares support
- verify object keys remain unchanged by the adapter
- verify grants expire or are treated as temporary
- verify no provider URL is persisted by application code

The local filesystem adapter must pass these tests before any cloud adapter is accepted.

## Browser Upload Contract

Browser uploads are coordinated through provider-neutral `UploadGrant` records. The API persists only `store_alias`, `object_key`, checksums, size, MIME type, and upload state. The browser may receive a temporary grant URL, but the URL is not durable product state.

Supported upload transport names are:

- `api_proxy`
- `single_put`
- `multipart`
- `resumable`

The local MVP implements only `api_proxy`. Future adapters may add other transports by returning the same `UploadGrant` shape without exposing bucket, namespace, account, signed URL, or provider resource terms to domain and application modules.

## Local Filesystem Adapter

The local adapter maps each logical store alias to a separate directory under the configured local blob root. For the MVP, `media_private` stores uploaded originals and `story_published` is reserved for sanitized published derivatives.

The adapter must:

- generate signed, expiring, single-object upload grants
- verify the expected `store_alias`, `object_key`, maximum size, and expiration before accepting bytes
- stream uploads to a temporary file and atomically rename on success
- reject path traversal, absolute paths, NUL bytes, unknown store aliases, and symbolic-link escapes
- implement `stat`, `open_reader`, `put`, `delete`, `exists`, upload grants, and download grants
- keep file bytes out of PostgreSQL

Contract tests live under `services/backend/tests/blob_store_contract.py` and must be reused unchanged by future OCI, S3, and GCS adapters.

## Runtime Identity Rules

Runtime identity is an adapter and deployment concern. Domain and application modules must not import provider SDK identity packages or expose provider identity terms in public types.

Allowed locations for provider runtime identity code:

- provider storage adapter
- provider composition root
- deploy configuration
- infra definitions

Provider-specific credentials, roles, service accounts, instance principals, workload identities, or equivalent concepts must not appear in domain or application contracts.

## Provider Configuration Rules

Provider-specific configuration belongs outside domain and application modules. It may appear in adapter configuration, composition roots, deployment manifests, or infrastructure definitions.

Configuration must map logical aliases to provider resources. The application asks for `originals` or `derivatives`; the adapter decides where that lives.

Configuration must not require code changes in domain or application modules when switching from local storage to OCI, AWS, GCP, or another provider.

## Cross-Provider Migration Strategy

Future cross-provider migration must preserve `object_key` values and verify checksums.

Migration steps:

1. Freeze or dual-write affected logical stores according to the migration plan.
2. Enumerate persisted `BlobRef` records by `store_alias`.
3. Copy each object to the destination adapter using the same `object_key`.
4. Verify `size_bytes` and checksum for every copied object.
5. Record migration status separately from product records.
6. Switch the logical `store_alias` mapping after verification.
7. Run provider contract tests against the destination adapter.
8. Keep rollback instructions until integrity checks and application smoke tests pass.

Product records should not change during migration unless a checksum correction or integrity error requires an explicit repair workflow.
