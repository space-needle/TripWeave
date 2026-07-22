# OCI MVP Deployment Runbook

This runbook prepares the already-working local MVP for one OCI Compute VM. It does not
authorize Terraform apply or destructive commands. Stop for explicit approval before applying
infrastructure or tearing it down.

## Target Topology

- One OCI Compute VM, preferably `VM.Standard.A1.Flex` on ARM64 Ampere.
- Web, API, worker, PostgreSQL/PostGIS, and Caddy run through production Docker Compose.
- OCI Object Storage is selected through the existing BlobStore adapter.
- Public HTTP/HTTPS terminates at Caddy.
- PostgreSQL is exposed only on the internal Docker network.
- SSH is restricted to the configured administrator CIDR.
- No Kubernetes, cloud queue, managed Redis, load balancer, or managed database.

Oracle documents `VM.Standard.A1.Flex` as an Always Free Ampere shape, with Always Free
tenancies equivalent to 2 OCPUs and 12 GB of memory for Ampere A1. Keep Terraform variables
inside that envelope unless intentionally changing the cost posture.

## OCI Prerequisites

- OCI tenancy and compartment.
- Region selected for both Compute and Object Storage.
- Local Terraform credentials for planning only.
- Administrator public SSH key.
- Administrator CIDR in `/32` or a narrow office/VPN range.
- Optional DNS name pointing later to the Terraform `instance_public_ip` output.

Do not put application secrets in Terraform variables. Secrets live in a root-owned VM file:

```sh
sudo install -d -m 0755 /etc/tripweave
sudo install -m 0600 deploy/prod.env.example /etc/tripweave/tripweave.env
sudo chown root:root /etc/tripweave/tripweave.env
sudoedit /etc/tripweave/tripweave.env
```

## Plan Checklist

```sh
cd infra/oci/production
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out tripweave.plan
terraform show tripweave.plan
```

Review before apply:

- Shape is ARM64 `VM.Standard.A1.Flex`.
- OCPU and memory remain within the intended free-tier budget.
- SSH ingress is only `admin_ssh_cidr`.
- Public ingress is only TCP 80 and 443.
- Buckets have `NoPublicAccess`.
- Object Storage CORS will be applied after bucket creation with the reviewed origin.
- Dynamic group matches only the created instance.
- Object Storage policy is limited to the TripWeave buckets and pre-authenticated requests.
- No application secret appears in plan output.

Stop here until explicit approval is given.

## Apply Checklist

Only after explicit approval:

```sh
cd infra/oci/production
terraform apply tripweave.plan
terraform output
```

Then SSH to the VM and install the application:

```sh
ssh ubuntu@<instance_public_ip>
sudo mkdir -p /opt/tripweave
sudo chown ubuntu:ubuntu /opt/tripweave
git clone <repo-url> /opt/tripweave/current
cd /opt/tripweave/current
sudo deploy/scripts/install-systemd.sh
sudo install -m 0600 deploy/prod.env.example /etc/tripweave/tripweave.env
sudo chown root:root /etc/tripweave/tripweave.env
sudoedit /etc/tripweave/tripweave.env
```

Use Terraform outputs for:

- `OCI_STORE_ALIAS_BUCKETS`
- `OCI_NAMESPACE`
- `PUBLIC_HOST`
- `PUBLIC_API_BASE_URL`
- `TRIPWEAVE_PUBLIC_API_BASE_URL`
- `TRIPWEAVE_ALLOWED_WEB_ORIGINS`

Apply CORS to each TripWeave bucket after editing `infra/oci/storage/cors-policy.json` with the
real origin:

```sh
oci os bucket update --namespace-name <namespace> --name <bucket> --cors-rules file://infra/oci/storage/cors-policy.json
```

## IP-Based Verification

Before DNS, keep:

```sh
TRIPWEAVE_SITE_ADDRESS=:80
PUBLIC_API_BASE_URL=http://<instance_public_ip>/api
TRIPWEAVE_PUBLIC_API_BASE_URL=http://<instance_public_ip>
TRIPWEAVE_ALLOWED_WEB_ORIGINS=http://<instance_public_ip>
```

Deploy:

```sh
cd /opt/tripweave/current
TRIPWEAVE_HEALTH_BASE_URL=http://<instance_public_ip> deploy/scripts/deploy.sh
curl -fsS http://<instance_public_ip>/api/health/ready
```

## DNS And HTTPS

After IP verification:

1. Point the DNS A record to `instance_public_ip`.
2. Update `/etc/tripweave/tripweave.env`:

```sh
TRIPWEAVE_SITE_ADDRESS=example.com
PUBLIC_API_BASE_URL=https://example.com/api
TRIPWEAVE_PUBLIC_API_BASE_URL=https://example.com
TRIPWEAVE_ALLOWED_WEB_ORIGINS=https://example.com
```

3. Redeploy:

```sh
TRIPWEAVE_HEALTH_BASE_URL=https://example.com deploy/scripts/deploy.sh
```

Caddy will request and renew HTTPS certificates automatically when DNS points to the VM.

## Upgrade

```sh
cd /opt/tripweave/current
git fetch --all
git checkout <approved-commit>
TRIPWEAVE_HEALTH_BASE_URL=https://example.com deploy/scripts/deploy.sh
```

The deployment script builds images, starts PostgreSQL, runs Alembic migrations before replacing
the app containers, then waits for readiness.

## Update An Existing VM From Local Changes

Use this when code was changed locally and needs to be applied to the existing single-VM
deployment.

Recommended path after committing and pushing:

```sh
# Local machine
make format
make lint
make typecheck
make test
make build
git status --short
git add <changed-files>
git commit -m "<message>"
git push

# VM
ssh -i ~/.ssh/tripweave_oci ubuntu@<instance_public_ip>
cd /opt/tripweave/current
git fetch --all
git checkout <commit-sha-or-branch>
sudo TRIPWEAVE_HEALTH_BASE_URL=https://<domain> deploy/scripts/deploy.sh
curl -fsS https://<domain>/api/health/ready
```

Current production values:

```sh
ssh -i ~/.ssh/tripweave_oci ubuntu@40.233.113.214
cd /opt/tripweave/current
sudo TRIPWEAVE_HEALTH_BASE_URL=https://tripweave.chronotrailai.com deploy/scripts/deploy.sh
curl -fsS https://tripweave.chronotrailai.com/api/health/ready
```

Hotfix path before pushing, for a small known file set:

```sh
# Local machine
scp -i ~/.ssh/tripweave_oci <local-file> ubuntu@<instance_public_ip>:/tmp/<file>
ssh -i ~/.ssh/tripweave_oci ubuntu@<instance_public_ip> \
  sudo install -m 0644 /tmp/<file> /opt/tripweave/current/<local-file>

# VM or remote ssh command
cd /opt/tripweave/current
sudo TRIPWEAVE_HEALTH_BASE_URL=https://<domain> deploy/scripts/deploy.sh
curl -fsS https://<domain>/api/health/ready
```

If the change affects existing story reconstruction data, run the affected trip through the
deployed backend after the deploy:

```sh
cd /opt/tripweave/current
sudo docker compose --env-file /etc/tripweave/tripweave.env -f deploy/compose.prod.yml exec -T api \
  .venv/bin/python -c "from uuid import UUID; from sqlalchemy.orm import Session; from tripweave.config import Settings; from tripweave.adapters.database import create_database_engine; from tripweave.adapters.geocoder_factory import create_geocoder; from tripweave.adapters import orm; from tripweave.adapters.reconstruction import reconstruct_trip; settings=Settings(); engine=create_database_engine(settings); geocoder=create_geocoder(settings); db=Session(engine); trip=db.get(orm.Trip, UUID('<trip-id>')); assert trip is not None; print(reconstruct_trip(db=db, trip=trip, geocoder=geocoder)); db.close()"
```

Do not copy `.env`, `terraform.tfvars`, private keys, API tokens, or other secrets into the repo.

## Rollback

```sh
cd /opt/tripweave/current
git checkout <previous-known-good-commit>
TRIPWEAVE_HEALTH_BASE_URL=https://example.com deploy/scripts/deploy.sh
```

If a database migration was already applied, review the Alembic downgrade path and backup status
before rolling back application code.

## Backups

Daily backup command:

```sh
cd /opt/tripweave/current
deploy/scripts/backup.sh
```

Recommended cron:

```cron
17 10 * * * cd /opt/tripweave/current && deploy/scripts/backup.sh >> /var/log/tripweave-backup.log 2>&1
```

Backups are compressed custom-format `pg_dump` files uploaded through the provider-neutral
`tripweave-backup` command using the configured BlobStore adapter. OCI lifecycle rules retain
`db_backups/postgres/` objects for `backup_retention_days`.

## Restore Drill

Restore into a separate database first:

```sh
cd /opt/tripweave/current
deploy/scripts/restore.sh postgres/tripweave-YYYYMMDDTHHMMSSZ.dump
```

This creates `tripweave_restore` by default. Do not replace production data until the restore is
verified and an explicit cutover plan exists.

## Teardown

Do not run destroy without explicit approval:

```sh
cd infra/oci/production
terraform plan -destroy -out tripweave-destroy.plan
terraform show tripweave-destroy.plan
# Stop for approval.
```

## Cost And Free-Tier Review

- Confirm the region is eligible for your free-tier resources.
- Confirm `instance_ocpus <= 2` and `instance_memory_gbs <= 12` for Always Free Ampere A1.
- Confirm there is one VM and no load balancer, managed database, Kubernetes, Redis, or queue.
- Confirm bucket storage and egress usage stay within your intended budget.
- Confirm boot volume size is intentional.
