locals {
  stores = {
    media_private   = "${var.bucket_prefix}-media-private"
    story_published = "${var.bucket_prefix}-story-published"
  }
}

resource "oci_objectstorage_bucket" "stores" {
  for_each       = local.stores
  compartment_id = var.compartment_id
  name           = each.value
  namespace      = data.oci_objectstorage_namespace.current.namespace
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"

  versioning = "Disabled"

  cors_rules {
    allowed_origins = var.allowed_origins
    allowed_methods = ["GET", "HEAD", "PUT", "OPTIONS"]
    allowed_headers = ["content-type", "content-length"]
    exposed_headers = ["etag", "opc-request-id"]
    max_age_in_seconds = 300
  }
}

resource "oci_objectstorage_object_lifecycle_policy" "temporary_incoming_cleanup" {
  namespace = data.oci_objectstorage_namespace.current.namespace
  bucket    = oci_objectstorage_bucket.stores["media_private"].name

  rules {
    name        = "cleanup-temporary-incoming"
    action      = "DELETE"
    is_enabled  = true
    object_name_filter {
      inclusion_prefixes = ["tmp/", "incoming/tmp/"]
    }
    time_amount = 7
    time_unit   = "DAYS"
  }
}

data "oci_objectstorage_namespace" "current" {
  compartment_id = var.compartment_id
}

resource "oci_identity_policy" "tripweave_storage_runtime" {
  compartment_id = var.compartment_id
  name           = "${var.bucket_prefix}-storage-runtime"
  description    = "Least-privilege Object Storage access for TripWeave runtime instances."

  statements = [
    "Allow dynamic-group ${var.runtime_dynamic_group_name} to read buckets in compartment id ${var.compartment_id}",
    "Allow dynamic-group ${var.runtime_dynamic_group_name} to manage objects in compartment id ${var.compartment_id} where any {target.bucket.name='${local.stores.media_private}', target.bucket.name='${local.stores.story_published}'}",
    "Allow dynamic-group ${var.runtime_dynamic_group_name} to manage preauthrequests in compartment id ${var.compartment_id} where any {target.bucket.name='${local.stores.media_private}', target.bucket.name='${local.stores.story_published}'}",
  ]
}
