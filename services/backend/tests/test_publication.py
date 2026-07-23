from __future__ import annotations

from io import BytesIO

from tripweave.adapters.publication import copy_publication_assets
from tripweave.domain.storage import BlobRef

from .fake_blob_store import FakeInMemoryBlobStore


def test_copy_publication_assets_does_not_probe_public_objects() -> None:
    blob_store = FakeInMemoryBlobStore()
    source_ref = BlobRef(store_alias="media_private", object_key="assets/private/display.webp")
    public_ref = BlobRef(
        store_alias="story_published",
        object_key="trips/trip-1/story/assets/sha256/ab/abcdef.webp",
    )
    blob_store.put(
        source_ref,
        BytesIO(b"display-webp"),
        max_size_bytes=100,
        content_type="image/webp",
    )

    copy_publication_assets(
        blob_store,
        {
            "assets": [
                {
                    "sourceBlobRef": {
                        "storeAlias": source_ref.store_alias,
                        "objectKey": source_ref.object_key,
                    },
                    "blobRef": {
                        "storeAlias": public_ref.store_alias,
                        "objectKey": public_ref.object_key,
                        "sizeBytes": 12,
                    },
                    "mimeType": "image/webp",
                }
            ]
        },
    )

    assert blob_store.exists_calls == []
    with blob_store.open_reader(public_ref) as reader:
        assert reader.read() == b"display-webp"


def test_copy_publication_assets_skips_known_public_keys_without_probe() -> None:
    blob_store = FakeInMemoryBlobStore()
    source_ref = BlobRef(store_alias="media_private", object_key="assets/private/display.webp")
    public_ref = BlobRef(
        store_alias="story_published",
        object_key="trips/trip-1/story/assets/sha256/ab/abcdef.webp",
    )
    blob_store.put(
        source_ref,
        BytesIO(b"display-webp"),
        max_size_bytes=100,
        content_type="image/webp",
    )

    copy_publication_assets(
        blob_store,
        {
            "assets": [
                {
                    "sourceBlobRef": {
                        "storeAlias": source_ref.store_alias,
                        "objectKey": source_ref.object_key,
                    },
                    "blobRef": {
                        "storeAlias": public_ref.store_alias,
                        "objectKey": public_ref.object_key,
                        "sizeBytes": 12,
                    },
                    "mimeType": "image/webp",
                }
            ]
        },
        existing_public_asset_keys={public_ref.object_key},
    )

    assert blob_store.exists_calls == []
    assert not blob_store.exists(public_ref)
