from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import secrets
import tempfile
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, cast

from tripweave.adapters.local_blob_store import (
    BlobNotFoundError,
    BlobSizeExceededError,
    InvalidGrantError,
)
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

CHUNK_SIZE = 1024 * 1024
PAR_ACCESS_TYPE_OBJECT_READ = "ObjectRead"
PAR_ACCESS_TYPE_OBJECT_WRITE = "ObjectWrite"


class OciBlobStore:
    def __init__(
        self,
        *,
        namespace: str,
        region: str,
        alias_to_bucket: dict[str, str],
        object_storage_client: Any,
        public_api_base_url: str,
        signing_secret: str,
        grant_lifetime_seconds: int,
        maximum_single_upload_bytes: int,
        use_single_put_grants: bool = True,
    ) -> None:
        if not namespace:
            raise ValueError("OCI namespace is required")
        if not region:
            raise ValueError("OCI region is required")
        if not alias_to_bucket:
            raise ValueError("OCI store alias mapping is required")
        self._namespace = namespace
        self._region = region
        self._alias_to_bucket = dict(alias_to_bucket)
        self._client = object_storage_client
        self._public_api_base_url = public_api_base_url.rstrip("/")
        self._signing_secret = signing_secret.encode("utf-8")
        self._grant_lifetime_seconds = grant_lifetime_seconds
        self._capabilities = StorageCapabilities(
            supports_api_proxy_upload=True,
            supports_single_put_upload=use_single_put_grants,
            supports_resumable_upload=False,
            supports_ranged_read=False,
            supports_direct_upload=use_single_put_grants,
            supports_direct_download=True,
            supports_server_side_copy=False,
            supports_multipart_upload=False,
            supports_conditional_write=False,
            supports_checksum_verification=True,
            supports_temporary_grants=True,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            recommended_part_size_bytes=CHUNK_SIZE,
        )

    @classmethod
    def from_instance_principal(
        cls,
        *,
        namespace: str,
        region: str,
        alias_to_bucket: dict[str, str],
        public_api_base_url: str,
        signing_secret: str,
        grant_lifetime_seconds: int,
        maximum_single_upload_bytes: int,
        use_single_put_grants: bool,
    ) -> OciBlobStore:
        oci = _load_oci()
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        client = oci.object_storage.ObjectStorageClient(
            {"region": region},
            signer=signer,
        )
        return cls(
            namespace=namespace,
            region=region,
            alias_to_bucket=alias_to_bucket,
            object_storage_client=client,
            public_api_base_url=public_api_base_url,
            signing_secret=signing_secret,
            grant_lifetime_seconds=grant_lifetime_seconds,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            use_single_put_grants=use_single_put_grants,
        )

    @classmethod
    def from_config_profile(
        cls,
        *,
        namespace: str,
        config_file: str,
        profile: str,
        alias_to_bucket: dict[str, str],
        public_api_base_url: str,
        signing_secret: str,
        grant_lifetime_seconds: int,
        maximum_single_upload_bytes: int,
        use_single_put_grants: bool,
    ) -> OciBlobStore:
        oci = _load_oci()
        config = oci.config.from_file(file_location=config_file, profile_name=profile)
        region = str(config["region"])
        client = oci.object_storage.ObjectStorageClient(config)
        return cls(
            namespace=namespace,
            region=region,
            alias_to_bucket=alias_to_bucket,
            object_storage_client=client,
            public_api_base_url=public_api_base_url,
            signing_secret=signing_secret,
            grant_lifetime_seconds=grant_lifetime_seconds,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            use_single_put_grants=use_single_put_grants,
        )

    @property
    def capabilities(self) -> StorageCapabilities:
        return self._capabilities

    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant:
        expires_at = request.expires_at or datetime.now(UTC) + timedelta(
            seconds=self._grant_lifetime_seconds
        )
        if request.transport == UploadTransport.API_PROXY:
            token = self._make_proxy_token(request, expires_at)
            return UploadGrant(
                blob_ref=request.blob_ref,
                method=UploadTransport.API_PROXY,
                url=f"{self._public_api_base_url}/blob-upload/{token}",
                headers={"content-type": request.content_type or "application/octet-stream"},
                expires_at=expires_at,
                max_size_bytes=request.max_size_bytes,
                content_type=request.content_type,
            )
        if request.transport != UploadTransport.SINGLE_PUT:
            raise ValueError("OCI blob store currently supports api_proxy and single_put")
        if not self._capabilities.supports_single_put_upload:
            raise ValueError("OCI single_put upload grants are disabled")
        bucket_name = self._bucket_name(request.blob_ref)
        details = self._par_details(
            name=f"tripweave-upload-{hashlib.sha256(request.blob_ref.object_key.encode()).hexdigest()[:24]}",
            access_type=PAR_ACCESS_TYPE_OBJECT_WRITE,
            object_name=request.blob_ref.object_key,
            expires_at=expires_at,
        )
        response = self._client.create_preauthenticated_request(
            namespace_name=self._namespace,
            bucket_name=bucket_name,
            create_preauthenticated_request_details=details,
        )
        access_uri = str(response.data.access_uri)
        return UploadGrant(
            blob_ref=request.blob_ref,
            method=UploadTransport.SINGLE_PUT,
            url=self._par_url(access_uri),
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
        expires_at = request.expires_at or datetime.now(UTC) + timedelta(
            seconds=self._grant_lifetime_seconds
        )
        try:
            bucket_name = self._bucket_name(request.blob_ref)
            details = self._par_details(
                name=f"tripweave-download-{hashlib.sha256(request.blob_ref.object_key.encode()).hexdigest()[:24]}",
                access_type=PAR_ACCESS_TYPE_OBJECT_READ,
                object_name=request.blob_ref.object_key,
                expires_at=expires_at,
            )
            response = self._client.create_preauthenticated_request(
                namespace_name=self._namespace,
                bucket_name=bucket_name,
                create_preauthenticated_request_details=details,
            )
            url = self._par_url(str(response.data.access_uri))
            method = "direct_get"
        except Exception:
            url = (
                f"{self._public_api_base_url}/blob-download/"
                f"{self._make_download_proxy_token(request, expires_at)}"
            )
            method = "api_proxy"
        return DownloadGrant(
            blob_ref=request.blob_ref,
            method=method,
            url=url,
            headers={},
            expires_at=expires_at,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    def verify_upload_token(self, token: str) -> tuple[BlobRef, int, str | None]:
        payload = self._verify_token(token)
        try:
            max_size_bytes = payload["max_size_bytes"]
            if not isinstance(max_size_bytes, int):
                raise ValueError("max_size_bytes must be an integer")
            return (
                BlobRef(
                    store_alias=str(payload["store_alias"]),
                    object_key=str(payload["object_key"]),
                ),
                max_size_bytes,
                cast(str | None, payload.get("content_type")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidGrantError("invalid upload grant") from exc

    def verify_download_token(self, token: str) -> BlobRef:
        payload = self._verify_token(token)
        if payload.get("purpose") != "download":
            raise InvalidGrantError("invalid download grant")
        try:
            return BlobRef(
                store_alias=str(payload["store_alias"]),
                object_key=str(payload["object_key"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidGrantError("invalid download grant") from exc

    def stat(self, blob_ref: BlobRef) -> BlobMetadata:
        try:
            response = self._client.head_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name(blob_ref),
                object_name=blob_ref.object_key,
            )
        except Exception as exc:
            if _is_not_found(exc):
                raise BlobNotFoundError("blob not found") from exc
            raise
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        size_bytes = int(headers.get("content-length", "0"))
        content_type = headers.get("content-type")
        checksum = headers.get("opc-meta-sha256") or self._sha256_for_object(blob_ref)
        return BlobMetadata(
            blob_ref=BlobRef(
                store_alias=blob_ref.store_alias,
                object_key=blob_ref.object_key,
                checksum_algorithm="sha256",
                checksum=checksum,
                size_bytes=size_bytes,
                content_type=content_type,
            ),
            size_bytes=size_bytes,
            checksum_algorithm="sha256",
            checksum=checksum,
            content_type=content_type,
        )

    @contextmanager
    def open_reader(self, blob_ref: BlobRef) -> Iterator[BinaryIO]:
        try:
            response = self._client.get_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name(blob_ref),
                object_name=blob_ref.object_key,
            )
        except Exception as exc:
            if _is_not_found(exc):
                raise BlobNotFoundError("blob not found") from exc
            raise
        stream = response.data.raw
        try:
            yield cast(BinaryIO, stream)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    def put(
        self,
        blob_ref: BlobRef,
        reader: BinaryIO,
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata:
        buffered, checksum, size_bytes = _buffer_with_limit(reader, max_size_bytes)
        try:
            self._client.put_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name(blob_ref),
                object_name=blob_ref.object_key,
                put_object_body=buffered,
                content_type=content_type,
                content_length=size_bytes,
                opc_meta={"sha256": checksum},
            )
        finally:
            buffered.close()
        return self.stat(blob_ref)

    async def put_chunks(
        self,
        blob_ref: BlobRef,
        chunks: AsyncIterator[bytes],
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata:
        spooled = tempfile.SpooledTemporaryFile(max_size=8 * CHUNK_SIZE)  # noqa: SIM115
        hasher = hashlib.sha256()
        total = 0
        try:
            async for chunk in chunks:
                total += len(chunk)
                if total > max_size_bytes:
                    raise BlobSizeExceededError("blob exceeds maximum size")
                hasher.update(chunk)
                spooled.write(chunk)
            spooled.seek(0)
            self._client.put_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name(blob_ref),
                object_name=blob_ref.object_key,
                put_object_body=spooled,
                content_type=content_type,
                content_length=total,
                opc_meta={"sha256": hasher.hexdigest()},
            )
        finally:
            spooled.close()
        return self.stat(blob_ref)

    def delete(self, blob_ref: BlobRef) -> None:
        try:
            self._client.delete_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name(blob_ref),
                object_name=blob_ref.object_key,
            )
        except Exception as exc:
            if not _is_not_found(exc):
                raise

    def exists(self, blob_ref: BlobRef) -> bool:
        try:
            self.stat(blob_ref)
        except BlobNotFoundError:
            return False
        return True

    def _bucket_name(self, blob_ref: BlobRef) -> str:
        _validate_object_key(blob_ref.object_key)
        try:
            return self._alias_to_bucket[blob_ref.store_alias]
        except KeyError as exc:
            raise ValueError("unknown store_alias") from exc

    def _par_details(
        self,
        *,
        name: str,
        access_type: str,
        object_name: str,
        expires_at: datetime,
    ) -> Any:
        oci = _load_oci()
        return oci.object_storage.models.CreatePreauthenticatedRequestDetails(
            name=name,
            access_type=access_type,
            object_name=object_name,
            time_expires=expires_at,
        )

    def _par_url(self, access_uri: str) -> str:
        return f"https://objectstorage.{self._region}.oraclecloud.com{access_uri}"

    def _make_proxy_token(self, request: UploadGrantRequest, expires_at: datetime) -> str:
        # API proxy is a fallback for environments where browser direct PUT is unavailable.
        return self._sign_payload(
            {
                "store_alias": request.blob_ref.store_alias,
                "object_key": request.blob_ref.object_key,
                "max_size_bytes": request.max_size_bytes,
                "content_type": request.content_type,
                "expires_at": int(expires_at.timestamp()),
                "nonce": secrets.token_urlsafe(16),
            }
        )

    def _make_download_proxy_token(
        self, request: DownloadGrantRequest, expires_at: datetime
    ) -> str:
        return self._sign_payload(
            {
                "store_alias": request.blob_ref.store_alias,
                "object_key": request.blob_ref.object_key,
                "expires_at": int(expires_at.timestamp()),
                "purpose": "download",
                "nonce": secrets.token_urlsafe(16),
            }
        )

    def _sign_payload(self, payload: dict[str, object]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_secret, body, hashlib.sha256).digest()
        return ".".join(
            [
                urlsafe_b64encode(body).decode("ascii").rstrip("="),
                urlsafe_b64encode(signature).decode("ascii").rstrip("="),
            ]
        )

    def _verify_token(self, token: str) -> dict[str, object]:
        try:
            body_part, signature_part = token.split(".", 1)
            body = _b64decode(body_part)
            signature = _b64decode(signature_part)
        except ValueError as exc:
            raise InvalidGrantError("invalid grant token") from exc
        expected = hmac.new(self._signing_secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidGrantError("invalid grant token")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidGrantError("invalid grant token")
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, int) or datetime.now(UTC).timestamp() > expires_at:
            raise InvalidGrantError("grant token expired")
        return cast(dict[str, object], payload)

    def _sha256_for_object(self, blob_ref: BlobRef) -> str:
        hasher = hashlib.sha256()
        with self.open_reader(blob_ref) as reader:
            for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


def _load_oci() -> Any:
    try:
        return importlib.import_module("oci")
    except ImportError as exc:
        raise RuntimeError(
            "OCI storage adapter requires installing the backend oci dependency group"
        ) from exc


def _buffer_with_limit(reader: BinaryIO, max_size_bytes: int) -> tuple[BinaryIO, str, int]:
    spooled = tempfile.SpooledTemporaryFile(max_size=8 * CHUNK_SIZE)  # noqa: SIM115
    hasher = hashlib.sha256()
    total = 0
    try:
        for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
            total += len(chunk)
            if total > max_size_bytes:
                raise BlobSizeExceededError("blob exceeds maximum size")
            hasher.update(chunk)
            spooled.write(chunk)
        spooled.seek(0)
        return cast(BinaryIO, spooled), hasher.hexdigest(), total
    except Exception:
        spooled.close()
        raise


def _validate_object_key(object_key: str) -> None:
    if object_key.startswith("/") or "\x00" in object_key:
        raise ValueError("invalid object_key")
    parts = object_key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid object_key")


def _is_not_found(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 404


def _b64decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return urlsafe_b64decode(padded.encode("ascii"))
