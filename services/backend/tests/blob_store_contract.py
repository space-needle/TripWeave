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
from tripweave.domain.storage import BlobRef, DownloadGrantRequest, UploadGrant, UploadGrantRequest
from tripweave.ports.blob_store import BlobStore


class GrantVerifyingBlobStore(Protocol):
    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant: ...

    def verify_upload_token(self, token: str) -> tuple[BlobRef, int, str | None]: ...


def run_blob_store_contract(make_store: Callable[[], BlobStore]) -> None:
    store = make_store()
    blob_ref = BlobRef(store_alias="media_private", object_key="trip/a/photo.jpg")

    grant = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=blob_ref,
            max_size_bytes=32,
            content_type="image/jpeg",
        )
    )

    assert grant.method == "api_proxy"
    assert grant.blob_ref == blob_ref
    assert grant.max_size_bytes == 32
    assert "bucket" not in grant.url.lower()
    assert "namespace" not in grant.url.lower()

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
