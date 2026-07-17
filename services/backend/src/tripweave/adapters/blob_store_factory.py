from tripweave.adapters.local_blob_store import LocalBlobStore
from tripweave.config import Settings
from tripweave.ports.blob_store import BlobStore


def create_blob_store(settings: Settings) -> BlobStore:
    match settings.storage_adapter:
        case "local":
            return LocalBlobStore(
                root=settings.blob_dir,
                store_aliases=settings.store_aliases,
                signing_secret=settings.storage_signing_secret,
                public_base_url=settings.public_api_base_url,
                grant_lifetime_seconds=settings.upload_grant_lifetime_seconds,
                maximum_single_upload_bytes=settings.upload_max_file_bytes,
            )
        case "oci":
            from tripweave.adapters.storage.oci.blob_store import OciBlobStore

            alias_to_bucket = settings.oci_alias_to_bucket
            missing_aliases = settings.store_aliases - set(alias_to_bucket)
            if missing_aliases:
                missing = ", ".join(sorted(missing_aliases))
                raise ValueError(f"Missing OCI bucket mapping for aliases: {missing}")
            if not settings.oci_namespace:
                raise ValueError("TRIPWEAVE_OCI_NAMESPACE is required for OCI storage")
            if settings.oci_auth_mode == "instance_principal":
                if not settings.oci_region:
                    raise ValueError(
                        "TRIPWEAVE_OCI_REGION is required for OCI instance principal storage"
                    )
                return OciBlobStore.from_instance_principal(
                    namespace=settings.oci_namespace,
                    region=settings.oci_region,
                    alias_to_bucket=alias_to_bucket,
                    public_api_base_url=settings.public_api_base_url,
                    signing_secret=settings.storage_signing_secret,
                    grant_lifetime_seconds=settings.upload_grant_lifetime_seconds,
                    maximum_single_upload_bytes=settings.upload_max_file_bytes,
                    use_single_put_grants=settings.oci_use_single_put_grants,
                )
            if settings.oci_auth_mode == "config_profile":
                return OciBlobStore.from_config_profile(
                    namespace=settings.oci_namespace,
                    config_file=settings.oci_config_file,
                    profile=settings.oci_config_profile,
                    alias_to_bucket=alias_to_bucket,
                    public_api_base_url=settings.public_api_base_url,
                    signing_secret=settings.storage_signing_secret,
                    grant_lifetime_seconds=settings.upload_grant_lifetime_seconds,
                    maximum_single_upload_bytes=settings.upload_max_file_bytes,
                    use_single_put_grants=settings.oci_use_single_put_grants,
                )
            raise ValueError(f"Unsupported OCI auth mode: {settings.oci_auth_mode}")
        case _:
            raise ValueError(f"Unsupported storage adapter: {settings.storage_adapter}")
