from __future__ import annotations

from pathlib import Path

import pytest

from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.adapters.local_blob_store import LocalBlobStore
from tripweave.config import Settings


def test_unselected_provider_namespace_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWEAVE_OCI_NAMESPACE", "ignored-unless-oci-is-selected")
    settings = Settings(
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_STORAGE_ADAPTER="local",
        TRIPWEAVE_STORAGE_SIGNING_SECRET="unit-test-signing-secret",
    )

    assert settings.storage_adapter == "local"
    assert not hasattr(settings, "oci_namespace")
    assert isinstance(create_blob_store(settings), LocalBlobStore)


def test_unknown_storage_adapter_fails_in_composition_root(tmp_path: Path) -> None:
    settings = Settings(
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_STORAGE_ADAPTER="future_adapter",
        TRIPWEAVE_STORAGE_SIGNING_SECRET="unit-test-signing-secret",
    )

    with pytest.raises(ValueError, match="Unsupported storage adapter"):
        create_blob_store(settings)
