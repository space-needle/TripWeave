variable "region" {
  description = "OCI region for Compute and Object Storage."
  type        = string
}

variable "compartment_id" {
  description = "OCI compartment OCID for all TripWeave resources."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain name. Leave null to use the first available domain."
  type        = string
  default     = null
}

variable "deployment_name" {
  description = "Name prefix for OCI resources."
  type        = string
  default     = "tripweave-mvp"
}

variable "admin_ssh_cidr" {
  description = "Administrator CIDR allowed to SSH to the VM."
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key installed for the default ubuntu user."
  type        = string
}

variable "vcn_cidr" {
  description = "VCN CIDR block."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Public subnet CIDR block."
  type        = string
  default     = "10.42.1.0/24"
}

variable "instance_shape" {
  description = "Free-tier-friendly ARM64 shape."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "instance_ocpus" {
  description = "Ampere A1 OCPUs. Keep within free-tier allocation."
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Ampere A1 memory in GB. Keep within free-tier allocation."
  type        = number
  default     = 12
}

variable "boot_volume_size_gbs" {
  description = "Boot volume size in GB."
  type        = number
  default     = 100
}

variable "bucket_prefix" {
  description = "Prefix for private Object Storage buckets."
  type        = string
  default     = "tripweave"
}

variable "backup_retention_days" {
  description = "Object lifecycle retention for database backups."
  type        = number
  default     = 14
}
