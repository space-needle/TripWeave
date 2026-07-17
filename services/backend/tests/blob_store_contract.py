from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Protocol

import pytest

from tripweave.adapters.local_blob_store import (
    BlobNotFoundError,
    BlobSizeExceededError,
    InvalidGrantError,
)
from tripweave.domain.storage import (
    BlobRef,
    DownloadGrantRequest,
    UploadGrant,
    UploadGrantRequest,
    UploadTransport,
)
from tripweave.ports.blob_store import BlobStore


class GrantVerifyingBlobStore(Protocol):
    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant: ...

    def verify_upload_token(self, token: str) -> tuple[BlobRef, int, str | None]: ...


def run_blob_store_contract(make_store: Callable[[], BlobStore]) -> None:
    store = make_store()
    blob_ref = BlobRef(store_alias="media_private", object_key="trip/a/photo.jpg")
    capabilities = store.capabilities

    assert capabilities.supports_api_proxy_upload
    assert capabilities.supports_checksum_verification
    assert capabilities.supports_temporary_grants
    assert capabilities.maximum_single_upload_bytes > 0
    assert capabilities.recommended_part_size_bytes > 0
    assert isinstance(capabilities.supports_multipart_upload, bool)
    assert isinstance(capabilities.supports_single_put_upload, bool)
    assert isinstance(capabilities.supports_resumable_upload, bool)
    assert isinstance(capabilities.supports_ranged_read, bool)
    assert isinstance(capabilities.supports_server_side_copy, bool)

    grant = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=blob_ref,
            max_size_bytes=32,
            content_type="image/jpeg",
        )
    )

    assert grant.method == UploadTransport.API_PROXY
    assert grant.blob_ref == blob_ref
    assert grant.max_size_bytes == 32
    assert "bucket" not in grant.url.lower()
    assert "namespace" not in grant.url.lower()
    assert "presigned" not in grant.url.lower()

    metadata = store.put(
        blob_ref,
        BytesIO(b"jpeg-bytes"),
        max_size_bytes=32,
        content_type="image/jpeg",
    )
    assert metadata.size_bytes == len(b"jpeg-bytes")
    assert metadata.checksum_algorithm == "sha256"
    assert metadata.content_type == "image/jpeg"
    assert store.exists(blob_ref)
    assert store.stat(blob_ref).checksum == metadata.checksum

    with store.open_reader(blob_ref) as reader:
        assert reader.read() == b"jpeg-bytes"

    download = store.create_download_grant(DownloadGrantRequest(blob_ref=blob_ref))
    assert download.method == "api_proxy"
    assert "bucket" not in download.url.lower()
    assert "namespace" not in download.url.lower()

    with pytest.raises(BlobSizeExceededError):
        store.put(
            BlobRef(store_alias="media_private", object_key="trip/a/large.jpg"),
            BytesIO(b"too-large"),
            max_size_bytes=3,
            content_type="image/jpeg",
        )

    store.delete(blob_ref)
    assert not store.exists(blob_ref)
    with pytest.raises(BlobNotFoundError):
        store.stat(blob_ref)

    private_ref = BlobRef(store_alias="media_private", object_key="same/key.jpg")
    story_ref = BlobRef(store_alias="story_published", object_key="same/key.jpg")
    private = store.put(private_ref, BytesIO(b"private"), max_size_bytes=20)
    story = store.put(story_ref, BytesIO(b"story"), max_size_bytes=20)
    assert private.checksum != story.checksum
    assert private.blob_ref.object_key == story.blob_ref.object_key
    assert private.blob_ref.store_alias == "media_private"
    assert story.blob_ref.store_alias == "story_published"

    for transport, supported in [
        (UploadTransport.SINGLE_PUT, capabilities.supports_single_put_upload),
        (UploadTransport.MULTIPART, capabilities.supports_multipart_upload),
        (UploadTransport.RESUMABLE, capabilities.supports_resumable_upload),
    ]:
        request = UploadGrantRequest(
            blob_ref=BlobRef(
                store_alias="media_private",
                object_key=f"trip/a/{transport.value}.jpg",
            ),
            max_size_bytes=32,
            content_type="image/jpeg",
            transport=transport,
        )
        if supported:
            assert store.create_upload_grant(request).method == transport
        else:
            with pytest.raises(ValueError):
                store.create_upload_grant(request)


def run_grant_contract(make_store: Callable[[], GrantVerifyingBlobStore]) -> None:
    store = make_store()
    blob_ref = BlobRef(store_alias="media_private", object_key="trip/a/grant.jpg")
    grant = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=blob_ref,
            max_size_bytes=8,
            content_type="image/jpeg",
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
    )
    verified_ref, max_size, content_type = store.verify_upload_token(grant.url.rsplit("/", 1)[-1])
    assert verified_ref == blob_ref
    assert max_size == 8
    assert content_type == "image/jpeg"

    expired = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=blob_ref,
            max_size_bytes=8,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    with pytest.raises(InvalidGrantError):
        store.verify_upload_token(expired.url.rsplit("/", 1)[-1])
