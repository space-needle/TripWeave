from __future__ import annotations

import os

import pytest

from tripweave.adapters.storage.oci.blob_store import OciBlobStore
from tripweave.domain.storage import BlobRef

from ..blob_store_contract import run_blob_store_contract

pytestmark = pytest.mark.skipif(
    os.environ.get("TRIPWEAVE_OCI_TESTS") != "1",
    reason="OCI integration tests require TRIPWEAVE_OCI_TESTS=1 and OCI credentials",
)


def make_oci_store() -> OciBlobStore:
    alias_to_bucket = _alias_mapping(os.environ["TRIPWEAVE_OCI_STORE_ALIAS_BUCKETS"])
    auth_mode = os.environ.get("TRIPWEAVE_OCI_AUTH_MODE", "config_profile")
    namespace = os.environ["TRIPWEAVE_OCI_NAMESPACE"]
    public_api_base_url = os.environ.get("TRIPWEAVE_PUBLIC_API_BASE_URL", "http://localhost:8000")
    signing_secret = os.environ.get(
        "TRIPWEAVE_STORAGE_SIGNING_SECRET", "oci-integration-test-secret"
    )
    grant_lifetime_seconds = int(os.environ.get("TRIPWEAVE_UPLOAD_GRANT_SECONDS", "900"))
    maximum_single_upload_bytes = int(
        os.environ.get("TRIPWEAVE_UPLOAD_MAX_FILE_BYTES", str(25 * 1024 * 1024))
    )
    use_single_put_grants = (
        os.environ.get("TRIPWEAVE_OCI_USE_SINGLE_PUT_GRANTS", "true").lower() == "true"
    )
    if auth_mode == "instance_principal":
        return OciBlobStore.from_instance_principal(
            namespace=namespace,
            region=os.environ["TRIPWEAVE_OCI_REGION"],
            alias_to_bucket=alias_to_bucket,
            public_api_base_url=public_api_base_url,
            signing_secret=signing_secret,
            grant_lifetime_seconds=grant_lifetime_seconds,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            use_single_put_grants=use_single_put_grants,
        )
    if auth_mode == "config_profile":
        return OciBlobStore.from_config_profile(
            namespace=namespace,
            config_file=os.environ.get("TRIPWEAVE_OCI_CONFIG_FILE", "~/.oci/config"),
            profile=os.environ.get("TRIPWEAVE_OCI_CONFIG_PROFILE", "DEFAULT"),
            alias_to_bucket=alias_to_bucket,
            public_api_base_url=public_api_base_url,
            signing_secret=signing_secret,
            grant_lifetime_seconds=grant_lifetime_seconds,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            use_single_put_grants=use_single_put_grants,
        )
    raise ValueError(f"unsupported OCI auth mode: {auth_mode}")


def test_oci_blob_store_contract() -> None:
    store = make_oci_store()
    try:
        run_blob_store_contract(lambda: store)
    finally:
        for blob_ref in [
            BlobRef(store_alias="media_private", object_key="trip/a/photo.jpg"),
            BlobRef(store_alias="media_private", object_key="trip/a/large.jpg"),
            BlobRef(store_alias="media_private", object_key="same/key.jpg"),
            BlobRef(store_alias="story_published", object_key="same/key.jpg"),
            BlobRef(store_alias="media_private", object_key="trip/a/single_put.jpg"),
            BlobRef(store_alias="media_private", object_key="trip/a/multipart.jpg"),
            BlobRef(store_alias="media_private", object_key="trip/a/resumable.jpg"),
        ]:
            store.delete(blob_ref)


def _alias_mapping(value: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in value.split(","):
        alias, separator, bucket = entry.partition("=")
        if not separator:
            raise ValueError("TRIPWEAVE_OCI_STORE_ALIAS_BUCKETS must use alias=bucket entries")
        mapping[alias.strip()] = bucket.strip()
    return mapping
