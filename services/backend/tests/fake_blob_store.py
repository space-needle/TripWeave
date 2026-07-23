from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO

from tripweave.adapters.local_blob_store import BlobNotFoundError, BlobSizeExceededError
from tripweave.domain.storage import (
    BlobMetadata,
    BlobRef,
    DownloadGrant,
    DownloadGrantRequest,
    StorageCapabilities,
    UploadGrant,
    UploadGrantRequest,
    UploadTransport,
)


@dataclass(frozen=True, slots=True)
class StoredBlob:
    payload: bytes
    content_type: str | None
    checksum: str


class FakeInMemoryBlobStore:
    def __init__(
        self,
        *,
        store_aliases: set[str] | None = None,
        public_base_url: str = "memory://tripweave",
        supported_transports: set[UploadTransport] | None = None,
    ) -> None:
        self._store_aliases = frozenset(store_aliases or {"media_private", "story_published"})
        self._public_base_url = public_base_url.rstrip("/")
        self._supported_transports = supported_transports or {UploadTransport.API_PROXY}
        self._blobs: dict[tuple[str, str], StoredBlob] = {}
        self.exists_calls: list[BlobRef] = []
        self._capabilities = StorageCapabilities(
            supports_api_proxy_upload=UploadTransport.API_PROXY in self._supported_transports,
            supports_single_put_upload=UploadTransport.SINGLE_PUT in self._supported_transports,
            supports_resumable_upload=UploadTransport.RESUMABLE in self._supported_transports,
            supports_ranged_read=True,
            supports_direct_upload=UploadTransport.SINGLE_PUT in self._supported_transports,
            supports_direct_download=True,
            supports_server_side_copy=True,
            supports_multipart_upload=UploadTransport.MULTIPART in self._supported_transports,
            supports_conditional_write=True,
            supports_checksum_verification=True,
            supports_temporary_grants=True,
            maximum_single_upload_bytes=1024 * 1024,
            recommended_part_size_bytes=256 * 1024,
        )

    @property
    def capabilities(self) -> StorageCapabilities:
        return self._capabilities

    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant:
        self._validate_ref(request.blob_ref)
        if request.transport not in self._supported_transports:
            raise ValueError(f"unsupported upload transport: {request.transport}")
        expires_at = request.expires_at or datetime.now(UTC) + timedelta(seconds=60)
        return UploadGrant(
            blob_ref=request.blob_ref,
            method=request.transport,
            url=f"{self._public_base_url}/upload/{request.blob_ref.store_alias}/{request.blob_ref.object_key}",
            headers={"content-type": request.content_type or "application/octet-stream"},
            expires_at=expires_at,
            max_size_bytes=request.max_size_bytes,
            content_type=request.content_type,
        )

    def create_download_grant(self, request: DownloadGrantRequest) -> DownloadGrant:
        metadata = None
        if request.blob_ref.size_bytes is None or request.blob_ref.content_type is None:
            metadata = self.stat(request.blob_ref)
        content_type = request.blob_ref.content_type
        if content_type is None and metadata is not None:
            content_type = metadata.content_type
        size_bytes = request.blob_ref.size_bytes
        if size_bytes is None and metadata is not None:
            size_bytes = metadata.size_bytes
        return DownloadGrant(
            blob_ref=request.blob_ref,
            method="api_proxy",
            url=f"{self._public_base_url}/download/{request.blob_ref.store_alias}/{request.blob_ref.object_key}",
            headers={},
            expires_at=request.expires_at or datetime.now(UTC) + timedelta(seconds=60),
            content_type=content_type,
            size_bytes=size_bytes,
        )

    def stat(self, blob_ref: BlobRef) -> BlobMetadata:
        self._validate_ref(blob_ref)
        stored = self._blobs.get(self._key(blob_ref))
        if stored is None:
            raise BlobNotFoundError("blob not found")
        return BlobMetadata(
            blob_ref=BlobRef(
                store_alias=blob_ref.store_alias,
                object_key=blob_ref.object_key,
                checksum_algorithm="sha256",
                checksum=stored.checksum,
                size_bytes=len(stored.payload),
                content_type=stored.content_type,
            ),
            size_bytes=len(stored.payload),
            checksum_algorithm="sha256",
            checksum=stored.checksum,
            content_type=stored.content_type,
        )

    @contextmanager
    def open_reader(self, blob_ref: BlobRef) -> Iterator[BinaryIO]:
        self._validate_ref(blob_ref)
        stored = self._blobs.get(self._key(blob_ref))
        if stored is None:
            raise BlobNotFoundError("blob not found")
        yield BytesIO(stored.payload)

    def put(
        self,
        blob_ref: BlobRef,
        reader: BinaryIO,
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata:
        self._validate_ref(blob_ref)
        payload = reader.read(max_size_bytes + 1)
        if len(payload) > max_size_bytes:
            raise BlobSizeExceededError("blob exceeds maximum size")
        checksum = hashlib.sha256(payload).hexdigest()
        self._blobs[self._key(blob_ref)] = StoredBlob(
            payload=payload,
            content_type=content_type,
            checksum=checksum,
        )
        return self.stat(blob_ref)

    def delete(self, blob_ref: BlobRef) -> None:
        self._validate_ref(blob_ref)
        self._blobs.pop(self._key(blob_ref), None)

    def exists(self, blob_ref: BlobRef) -> bool:
        self.exists_calls.append(blob_ref)
        try:
            self._validate_ref(blob_ref)
        except ValueError:
            return False
        return self._key(blob_ref) in self._blobs

    def _key(self, blob_ref: BlobRef) -> tuple[str, str]:
        return (blob_ref.store_alias, blob_ref.object_key)

    def _validate_ref(self, blob_ref: BlobRef) -> None:
        if blob_ref.store_alias not in self._store_aliases:
            raise ValueError("unknown store_alias")
        if blob_ref.object_key.startswith("/") or "\x00" in blob_ref.object_key:
            raise ValueError("invalid object_key")
        if any(part in {"", ".", ".."} for part in blob_ref.object_key.split("/")):
            raise ValueError("invalid object_key")
