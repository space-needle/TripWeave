from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class UploadTransport(StrEnum):
    API_PROXY = "api_proxy"
    SINGLE_PUT = "single_put"
    MULTIPART = "multipart"
    RESUMABLE = "resumable"


@dataclass(frozen=True, slots=True)
class BlobRef:
    store_alias: str
    object_key: str
    checksum_algorithm: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        if not self.store_alias:
            raise ValueError("store_alias is required")
        if not self.object_key:
            raise ValueError("object_key is required")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class BlobMetadata:
    blob_ref: BlobRef
    size_bytes: int
    checksum_algorithm: str
    checksum: str
    content_type: str | None = None

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class UploadGrantRequest:
    blob_ref: BlobRef
    max_size_bytes: int
    content_type: str | None = None
    expires_at: datetime | None = None
    transport: UploadTransport = UploadTransport.API_PROXY

    def __post_init__(self) -> None:
        if self.max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")


@dataclass(frozen=True, slots=True)
class UploadGrant:
    blob_ref: BlobRef
    method: UploadTransport
    url: str
    headers: dict[str, str]
    expires_at: datetime
    max_size_bytes: int
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadGrantRequest:
    blob_ref: BlobRef
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DownloadGrant:
    blob_ref: BlobRef
    method: str
    url: str
    headers: dict[str, str]
    expires_at: datetime
    content_type: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    supports_direct_upload: bool
    supports_direct_download: bool
    supports_server_side_copy: bool
    supports_multipart_upload: bool
    supports_conditional_write: bool
    supports_checksum_verification: bool
    supports_temporary_grants: bool
    maximum_single_upload_bytes: int
    recommended_part_size_bytes: int
