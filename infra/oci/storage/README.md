# OCI Storage-Only Infrastructure

This directory contains storage-only Terraform configuration for the TripWeave OCI adapter.
It is intentionally limited to private Object Storage buckets, lifecycle cleanup, and
least-privilege policies. Do not run `terraform apply` without explicit approval.

## Logical Store Mapping

The application persists only `store_alias` and `object_key`. Configure the adapter with:

```sh
TRIPWEAVE_STORAGE_ADAPTER=oci
TRIPWEAVE_OCI_AUTH_MODE=instance_principal
TRIPWEAVE_OCI_REGION=us-ashburn-1
TRIPWEAVE_OCI_NAMESPACE=<object-storage-namespace>
TRIPWEAVE_OCI_STORE_ALIAS_BUCKETS=media_private=<media-bucket>,story_published=<story-bucket>
```

For developer integration tests only, set `TRIPWEAVE_OCI_AUTH_MODE=config_profile` and point
`TRIPWEAVE_OCI_CONFIG_FILE` at a local OCI config. Never commit API private keys.

## CORS

Browser `single_put` upload grants require Object Storage CORS to allow the TripWeave web origin
to issue `PUT`, `GET`, `HEAD`, and `OPTIONS` requests with `content-type`. Configure
`allowed_origins` in `terraform.tfvars` to the deployed web origin before applying.

## Integration Tests

After creating disposable test buckets and configuring the environment:

```sh
TRIPWEAVE_OCI_TESTS=1 uv run --project services/backend --group oci pytest services/backend/tests/integration/test_oci_blob_store_contract.py
```

The test suite writes disposable objects and cleans them up in the configured buckets.
