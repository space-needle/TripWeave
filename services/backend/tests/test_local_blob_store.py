from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest

from tripweave.adapters.local_blob_store import InvalidGrantError, LocalBlobStore
from tripweave.domain.storage import BlobRef, UploadGrantRequest

from .blob_store_contract import run_blob_store_contract, run_grant_contract


class RecordingReader(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


def make_store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(
        root=tmp_path,
        store_aliases={"media_private", "story_published"},
        signing_secret="unit-test-signing-secret",
        public_base_url="http://api.test",
        grant_lifetime_seconds=60,
        maximum_single_upload_bytes=1024,
    )


def test_local_blob_store_contract(tmp_path: Path) -> None:
    run_blob_store_contract(lambda: make_store(tmp_path))


def test_local_upload_grant_contract(tmp_path: Path) -> None:
    run_grant_contract(lambda: make_store(tmp_path))


def test_prevents_path_traversal(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.put(
            BlobRef(store_alias="media_private", object_key="../escape.jpg"),
            BytesIO(b"x"),
            max_size_bytes=10,
        )


def test_prevents_symbolic_link_escape(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    alias_root = tmp_path / "media_private"
    alias_root.mkdir()
    (alias_root / "linked").symlink_to(outside)

    with pytest.raises(ValueError):
        store.put(
            BlobRef(store_alias="media_private", object_key="linked/file.jpg"),
            BytesIO(b"x"),
            max_size_bytes=10,
        )


def test_store_alias_isolation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    private_ref = BlobRef(store_alias="media_private", object_key="same/key.jpg")
    story_ref = BlobRef(store_alias="story_published", object_key="same/key.jpg")

    private = store.put(private_ref, BytesIO(b"private"), max_size_bytes=20)
    story = store.put(story_ref, BytesIO(b"story"), max_size_bytes=20)

    assert private.checksum != story.checksum
    with store.open_reader(private_ref) as reader:
        assert reader.read() == b"private"
    with store.open_reader(story_ref) as reader:
        assert reader.read() == b"story"


def test_upload_token_rejects_wrong_object_key_tampering(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    grant = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=BlobRef(store_alias="media_private", object_key="expected.jpg"),
            max_size_bytes=8,
        )
    )
    body, signature = grant.url.rsplit("/", 1)[-1].split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["object_key"] = "wrong.jpg"
    tampered_body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    )

    with pytest.raises(InvalidGrantError):
        store.verify_upload_token(f"{tampered_body}.{signature}")


def test_put_streams_in_bounded_chunks(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    reader = RecordingReader(b"x" * 32)

    store.put(
        BlobRef(store_alias="media_private", object_key="streamed.jpg"),
        reader,
        max_size_bytes=64,
    )

    assert reader.read_sizes[0] == 1024 * 1024
