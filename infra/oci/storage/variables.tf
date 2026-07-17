variable "compartment_id" {
  description = "OCI compartment OCID that owns the private storage buckets."
  type        = string
}

variable "bucket_prefix" {
  description = "Prefix for TripWeave private buckets."
  type        = string
  default     = "tripweave"
}

variable "runtime_dynamic_group_name" {
  description = "Dynamic group name for the deployed API/worker instance principals."
  type        = string
}

variable "backup_retention_days" {
  description = "Number of days to retain database backup objects."
  type        = number
  default     = 14
}
