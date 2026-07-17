from __future__ import annotations

from .blob_store_contract import run_blob_store_contract
from .fake_blob_store import FakeInMemoryBlobStore


def test_fake_blob_store_contract() -> None:
    run_blob_store_contract(lambda: FakeInMemoryBlobStore())
