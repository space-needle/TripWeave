from tripweave.adapters.local_blob_store import LocalBlobStore
from tripweave.config import Settings


def create_blob_store(settings: Settings) -> LocalBlobStore:
    if settings.storage_adapter != "local":
        raise ValueError(f"Unsupported storage adapter: {settings.storage_adapter}")
    return LocalBlobStore(
        root=settings.blob_dir,
        store_aliases=settings.store_aliases,
        signing_secret=settings.storage_signing_secret,
        public_base_url=settings.public_api_base_url,
        grant_lifetime_seconds=settings.upload_grant_lifetime_seconds,
        maximum_single_upload_bytes=settings.upload_max_file_bytes,
    )
