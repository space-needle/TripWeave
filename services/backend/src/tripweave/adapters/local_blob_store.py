from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

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


class BlobStoreError(Exception):
    pass


class BlobNotFoundError(BlobStoreError):
    pass


class InvalidGrantError(BlobStoreError):
    pass


class BlobSizeExceededError(BlobStoreError):
    pass


class LocalBlobStore:
    def __init__(
        self,
        *,
        root: Path,
        store_aliases: set[str],
        signing_secret: str,
        public_base_url: str,
        grant_lifetime_seconds: int,
        maximum_single_upload_bytes: int,
    ) -> None:
        if not signing_secret:
            raise ValueError("signing_secret is required")
        self._root = root
        self._store_aliases = frozenset(store_aliases)
        self._signing_secret = signing_secret.encode("utf-8")
        self._public_base_url = public_base_url.rstrip("/")
        self._grant_lifetime_seconds = grant_lifetime_seconds
        self._capabilities = StorageCapabilities(
            supports_api_proxy_upload=True,
            supports_single_put_upload=False,
            supports_resumable_upload=False,
            supports_ranged_read=False,
            supports_direct_upload=True,
            supports_direct_download=True,
            supports_server_side_copy=False,
            supports_multipart_upload=False,
            supports_conditional_write=False,
            supports_checksum_verification=True,
            supports_temporary_grants=True,
            maximum_single_upload_bytes=maximum_single_upload_bytes,
            recommended_part_size_bytes=CHUNK_SIZE,
        )

    @property
    def capabilities(self) -> StorageCapabilities:
        return self._capabilities

    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant:
        if request.transport != UploadTransport.API_PROXY:
            raise ValueError("local blob store currently supports only api_proxy")
        expires_at = request.expires_at or datetime.now(UTC) + timedelta(
            seconds=self._grant_lifetime_seconds
        )
        payload = {
            "store_alias": request.blob_ref.store_alias,
            "object_key": request.blob_ref.object_key,
            "max_size_bytes": request.max_size_bytes,
            "content_type": request.content_type,
            "expires_at": int(expires_at.timestamp()),
            "nonce": secrets.token_urlsafe(16),
        }
        token = self._sign_payload(payload)
        return UploadGrant(
            blob_ref=request.blob_ref,
            method=UploadTransport.API_PROXY,
            url=f"{self._public_base_url}/blob-upload/{token}",
            headers={
                "content-type": request.content_type or "application/octet-stream",
            },
            expires_at=expires_at,
            max_size_bytes=request.max_size_bytes,
            content_type=request.content_type,
        )

    def create_download_grant(self, request: DownloadGrantRequest) -> DownloadGrant:
        metadata = self.stat(request.blob_ref)
        expires_at = request.expires_at or datetime.now(UTC) + timedelta(
            seconds=self._grant_lifetime_seconds
        )
        payload = {
            "store_alias": request.blob_ref.store_alias,
            "object_key": request.blob_ref.object_key,
            "expires_at": int(expires_at.timestamp()),
            "nonce": secrets.token_urlsafe(16),
            "purpose": "download",
        }
        token = self._sign_payload(payload)
        return DownloadGrant(
            blob_ref=request.blob_ref,
            method="api_proxy",
            url=f"{self._public_base_url}/blob-download/{token}",
            headers={},
            expires_at=expires_at,
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
        )

    def verify_upload_token(self, token: str) -> tuple[BlobRef, int, str | None]:
        payload = self._verify_token(token)
        try:
            blob_ref = BlobRef(
                store_alias=str(payload["store_alias"]),
                object_key=str(payload["object_key"]),
            )
            max_size_bytes = int(payload["max_size_bytes"])
            content_type = payload.get("content_type")
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidGrantError("invalid upload grant") from exc
        if content_type is not None and not isinstance(content_type, str):
            raise InvalidGrantError("invalid upload grant")
        return blob_ref, max_size_bytes, content_type

    def verify_download_token(self, token: str) -> BlobRef:
        payload = self._verify_token(token)
        if payload.get("purpose") != "download":
            raise InvalidGrantError("invalid download grant")
        try:
            return BlobRef(
                store_alias=str(payload["store_alias"]),
                object_key=str(payload["object_key"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidGrantError("invalid download grant") from exc

    def stat(self, blob_ref: BlobRef) -> BlobMetadata:
        path = self._object_path(blob_ref)
        if not path.exists() or not path.is_file():
            raise BlobNotFoundError("blob not found")
        sidecar = self._read_sidecar(path)
        size_bytes = path.stat().st_size
        checksum = str(sidecar.get("checksum") or self._sha256_for_path(path))
        content_type = sidecar.get("content_type")
        return BlobMetadata(
            blob_ref=BlobRef(
                store_alias=blob_ref.store_alias,
                object_key=blob_ref.object_key,
                checksum_algorithm="sha256",
                checksum=checksum,
                size_bytes=size_bytes,
                content_type=str(content_type) if content_type else None,
            ),
            size_bytes=size_bytes,
            checksum_algorithm="sha256",
            checksum=checksum,
            content_type=str(content_type) if content_type else None,
        )

    @contextmanager
    def open_reader(self, blob_ref: BlobRef) -> Iterator[BinaryIO]:
        path = self._object_path(blob_ref)
        if not path.exists() or not path.is_file():
            raise BlobNotFoundError("blob not found")
        with path.open("rb") as handle:
            yield handle

    def put(
        self,
        blob_ref: BlobRef,
        reader: BinaryIO,
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata:
        path = self._object_path(blob_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        hasher = hashlib.sha256()
        total = 0
        try:
            with tmp_path.open("xb") as output:
                while True:
                    chunk = reader.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_size_bytes:
                        raise BlobSizeExceededError("blob exceeds maximum size")
                    hasher.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        metadata = {
            "checksum_algorithm": "sha256",
            "checksum": hasher.hexdigest(),
            "content_type": content_type,
            "size_bytes": total,
        }
        self._write_sidecar(path, metadata)
        return self.stat(blob_ref)

    async def put_chunks(
        self,
        blob_ref: BlobRef,
        chunks: AsyncIterator[bytes],
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata:
        path = self._object_path(blob_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        hasher = hashlib.sha256()
        total = 0
        try:
            with tmp_path.open("xb") as output:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_size_bytes:
                        raise BlobSizeExceededError("blob exceeds maximum size")
                    hasher.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        metadata = {
            "checksum_algorithm": "sha256",
            "checksum": hasher.hexdigest(),
            "content_type": content_type,
            "size_bytes": total,
        }
        self._write_sidecar(path, metadata)
        return self.stat(blob_ref)

    def delete(self, blob_ref: BlobRef) -> None:
        path = self._object_path(blob_ref)
        path.unlink(missing_ok=True)
        self._sidecar_path(path).unlink(missing_ok=True)

    def exists(self, blob_ref: BlobRef) -> bool:
        try:
            path = self._object_path(blob_ref)
        except ValueError:
            return False
        return path.exists() and path.is_file()

    def _object_path(self, blob_ref: BlobRef) -> Path:
        if blob_ref.store_alias not in self._store_aliases:
            raise ValueError("unknown store_alias")
        if blob_ref.object_key.startswith("/") or "\x00" in blob_ref.object_key:
            raise ValueError("invalid object_key")
        root = (self._root / blob_ref.store_alias).resolve()
        candidate = (root / blob_ref.object_key).resolve(strict=False)
        if root != candidate and root not in candidate.parents:
            raise ValueError("object_key escapes store root")
        if candidate.exists() and candidate.is_symlink():
            raise ValueError("object_key resolves to symlink")
        for parent in candidate.parents:
            if parent == root:
                break
            if parent.exists() and parent.is_symlink():
                raise ValueError("object_key parent resolves to symlink")
        return candidate

    def _sign_payload(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_secret, body, hashlib.sha256).digest()
        return ".".join(
            [
                base64.urlsafe_b64encode(body).decode("ascii").rstrip("="),
                base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
            ]
        )

    def _verify_token(self, token: str) -> dict[str, Any]:
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
        if int(payload["expires_at"]) < int(datetime.now(UTC).timestamp()):
            raise InvalidGrantError("grant has expired")
        return dict(payload)

    def _sidecar_path(self, path: Path) -> Path:
        return path.with_name(f"{path.name}.metadata.json")

    def _read_sidecar(self, path: Path) -> dict[str, Any]:
        sidecar = self._sidecar_path(path)
        if not sidecar.exists():
            return {}
        return dict(json.loads(sidecar.read_text(encoding="utf-8")))

    def _write_sidecar(self, path: Path, metadata: dict[str, Any]) -> None:
        sidecar = self._sidecar_path(path)
        tmp = sidecar.with_name(f".{sidecar.name}.{secrets.token_hex(8)}.tmp")
        tmp.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        os.replace(tmp, sidecar)

    def _sha256_for_path(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
