output "store_alias_bucket_mapping" {
  description = "Value for TRIPWEAVE_OCI_STORE_ALIAS_BUCKETS."
  value = join(",", [
    for alias, bucket in local.stores : "${alias}=${bucket}"
  ])
}

output "bucket_names" {
  value = local.stores
}
