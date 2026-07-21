locals {
  availability_domain = coalesce(
    var.availability_domain,
    data.oci_identity_availability_domains.ads.availability_domains[0].name,
  )
  common_freeform_tags = {
    TripWeaveDeployment = var.deployment_name
  }
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}

data "oci_core_images" "ubuntu_arm64" {
  compartment_id           = var.compartment_id
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "tripweave" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "${var.deployment_name}-vcn"
  dns_label      = "tripweave"
  freeform_tags  = local.common_freeform_tags
}

resource "oci_core_internet_gateway" "tripweave" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.tripweave.id
  display_name   = "${var.deployment_name}-igw"
  enabled        = true
  freeform_tags  = local.common_freeform_tags
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.tripweave.id
  display_name   = "${var.deployment_name}-public-routes"
  freeform_tags  = local.common_freeform_tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.tripweave.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.tripweave.id
  display_name   = "${var.deployment_name}-public-security"
  freeform_tags  = local.common_freeform_tags

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    description = "SSH from administrator CIDR"
    protocol    = "6"
    source      = var.admin_ssh_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    description = "Public HTTP"
    protocol    = "6"
    source      = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
  }

  ingress_security_rules {
    description = "Public HTTPS"
    protocol    = "6"
    source      = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.tripweave.id
  cidr_block                 = var.public_subnet_cidr
  display_name               = "${var.deployment_name}-public-subnet"
  dns_label                  = "public"
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.public.id]
  freeform_tags              = local.common_freeform_tags
}

resource "oci_core_instance" "tripweave" {
  availability_domain = local.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "${var.deployment_name}-vm"
  shape               = var.instance_shape
  freeform_tags       = local.common_freeform_tags

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  create_vnic_details {
    assign_public_ip = true
    subnet_id        = oci_core_subnet.public.id
    display_name     = "${var.deployment_name}-primary-vnic"
    hostname_label   = "tripweave"
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm64.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_size_gbs
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      admin_ssh_cidr = var.admin_ssh_cidr
    }))
  }
}

resource "oci_identity_dynamic_group" "tripweave_instance" {
  compartment_id = var.compartment_id
  name           = "${var.deployment_name}-instance-principal"
  description    = "TripWeave MVP VM instance principal."
  matching_rule  = "ALL {instance.id = '${oci_core_instance.tripweave.id}'}"
}

module "storage" {
  source                     = "../storage"
  compartment_id             = var.compartment_id
  bucket_prefix              = var.bucket_prefix
  region                     = var.region
  runtime_dynamic_group_name = oci_identity_dynamic_group.tripweave_instance.name
  backup_retention_days      = var.backup_retention_days
}
