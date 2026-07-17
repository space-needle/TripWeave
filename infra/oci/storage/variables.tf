variable "compartment_id" {
  description = "OCI compartment OCID that owns the private storage buckets."
  type        = string
}

variable "bucket_prefix" {
  description = "Prefix for TripWeave private buckets."
  type        = string
  default     = "tripweave"
}

variable "allowed_origins" {
  description = "Browser origins allowed to use temporary upload and download grants."
  type        = list(string)
  default     = []
}

variable "runtime_dynamic_group_name" {
  description = "Dynamic group name for the deployed API/worker instance principals."
  type        = string
}
