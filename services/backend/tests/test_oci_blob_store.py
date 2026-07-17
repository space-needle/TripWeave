from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace

from tripweave.adapters.storage.oci.blob_store import OciBlobStore
from tripweave.domain.storage import BlobRef, UploadGrantRequest, UploadTransport


@dataclass
class FakeResponse:
    data: object
    headers: dict[str, str]


class FakeOciNotFoundError(Exception):
    status = 404


class FakeOciObjectStorageClient:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], tuple[bytes, str | None, str]] = {}
        self.par_requests: list[dict[str, object]] = []

    def create_preauthenticated_request(
        self,
        *,
        namespace_name: str,
        bucket_name: str,
        create_preauthenticated_request_details: object,
    ) -> FakeResponse:
        self.par_requests.append(
            {
                "namespace": namespace_name,
                "bucket": bucket_name,
                "details": create_preauthenticated_request_details,
            }
        )
        return FakeResponse(
            data=SimpleNamespace(access_uri="/p/unit-test-par/n/ns/b/bucket/o/key"),
            headers={},
        )

    def put_object(
        self,
        *,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
        put_object_body: BytesIO,
        content_type: str | None,
        content_length: int,
        opc_meta: dict[str, str],
    ) -> FakeResponse:
        body = put_object_body.read()
        assert content_length == len(body)
        self.objects[(namespace_name, bucket_name, object_name)] = (
            body,
            content_type,
            opc_meta["sha256"],
        )
        return FakeResponse(data=object(), headers={})

    def head_object(
        self,
        *,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> FakeResponse:
        try:
            body, content_type, checksum = self.objects[(namespace_name, bucket_name, object_name)]
        except KeyError as exc:
            raise FakeOciNotFoundError from exc
        return FakeResponse(
            data=object(),
            headers={
                "content-length": str(len(body)),
                "content-type": content_type or "application/octet-stream",
                "opc-meta-sha256": checksum,
            },
        )

    def get_object(
        self,
        *,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> FakeResponse:
        try:
            body, _, _ = self.objects[(namespace_name, bucket_name, object_name)]
        except KeyError as exc:
            raise FakeOciNotFoundError from exc
        return FakeResponse(data=SimpleNamespace(raw=BytesIO(body)), headers={})

    def delete_object(
        self,
        *,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> FakeResponse:
        self.objects.pop((namespace_name, bucket_name, object_name), None)
        return FakeResponse(data=object(), headers={})


class _TestableOciBlobStore(OciBlobStore):
    def _par_details(
        self,
        *,
        name: str,
        access_type: str,
        object_name: str,
        expires_at: object,
    ) -> object:
        return SimpleNamespace(
            name=name,
            access_type=access_type,
            object_name=object_name,
            time_expires=expires_at,
        )


def make_store(client: FakeOciObjectStorageClient) -> _TestableOciBlobStore:
    return _TestableOciBlobStore(
        namespace="ns",
        region="us-ashburn-1",
        alias_to_bucket={
            "media_private": "tripweave-private",
            "story_published": "tripweave-story",
        },
        object_storage_client=client,
        public_api_base_url="http://api.test",
        signing_secret="unit-test-storage-secret",
        grant_lifetime_seconds=900,
        maximum_single_upload_bytes=25 * 1024 * 1024,
    )


def test_oci_put_stat_open_delete_with_logical_alias_mapping() -> None:
    client = FakeOciObjectStorageClient()
    store = make_store(client)
    blob_ref = BlobRef(store_alias="media_private", object_key="trip/1/photo.jpg")

    metadata = store.put(blob_ref, BytesIO(b"photo-bytes"), max_size_bytes=100)

    assert metadata.blob_ref.store_alias == "media_private"
    assert metadata.blob_ref.object_key == "trip/1/photo.jpg"
    assert ("ns", "tripweave-private", "trip/1/photo.jpg") in client.objects
    with store.open_reader(blob_ref) as reader:
        assert reader.read() == b"photo-bytes"
    assert store.exists(blob_ref)
    store.delete(blob_ref)
    assert not store.exists(blob_ref)


def test_oci_single_put_grant_is_object_specific_and_temporary() -> None:
    client = FakeOciObjectStorageClient()
    store = make_store(client)
    blob_ref = BlobRef(store_alias="media_private", object_key="trip/1/photo.jpg")

    grant = store.create_upload_grant(
        UploadGrantRequest(
            blob_ref=blob_ref,
            max_size_bytes=100,
            content_type="image/jpeg",
            transport=UploadTransport.SINGLE_PUT,
        )
    )

    assert grant.method == UploadTransport.SINGLE_PUT
    assert grant.blob_ref == blob_ref
    assert grant.headers == {"content-type": "image/jpeg"}
    assert client.par_requests
    details = client.par_requests[0]["details"]
    assert getattr(details, "access_type", None) == "ObjectWrite"
    assert getattr(details, "object_name", None) == "trip/1/photo.jpg"
