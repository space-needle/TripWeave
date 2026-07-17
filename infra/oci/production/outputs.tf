output "instance_public_ip" {
  description = "Public IP for IP-based verification and DNS setup."
  value       = oci_core_instance.tripweave.public_ip
}

output "ssh_command" {
  description = "SSH command for the default Ubuntu image user."
  value       = "ssh ubuntu@${oci_core_instance.tripweave.public_ip}"
}

output "store_alias_bucket_mapping" {
  description = "Value for OCI_STORE_ALIAS_BUCKETS in /etc/tripweave/tripweave.env."
  value       = module.storage.store_alias_bucket_mapping
}

output "bucket_names" {
  description = "Private Object Storage bucket names."
  value       = module.storage.bucket_names
}

output "deployment_note" {
  value = "Do not put secrets in Terraform variables. Create /etc/tripweave/tripweave.env manually on the VM."
}
