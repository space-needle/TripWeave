from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol

from tripweave.domain.storage import (
    BlobMetadata,
    BlobRef,
    DownloadGrant,
    DownloadGrantRequest,
    StorageCapabilities,
    UploadGrant,
    UploadGrantRequest,
)


class BlobStore(Protocol):
    @property
    def capabilities(self) -> StorageCapabilities: ...

    def create_upload_grant(self, request: UploadGrantRequest) -> UploadGrant: ...

    def create_download_grant(self, request: DownloadGrantRequest) -> DownloadGrant: ...

    def stat(self, blob_ref: BlobRef) -> BlobMetadata: ...

    def open_reader(self, blob_ref: BlobRef) -> AbstractContextManager[BinaryIO]: ...

    def put(
        self,
        blob_ref: BlobRef,
        reader: BinaryIO,
        *,
        max_size_bytes: int,
        content_type: str | None = None,
    ) -> BlobMetadata: ...

    def delete(self, blob_ref: BlobRef) -> None: ...

    def exists(self, blob_ref: BlobRef) -> bool: ...
