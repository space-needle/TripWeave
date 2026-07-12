# TripWeave Agent Instructions

TripWeave is built local-first and cloud-agnostic. Future Codex tasks must preserve that direction unless the user explicitly requests the stage that changes it.

## Required Reading

Before making changes, read:

- `README.md`
- `docs/architecture.md`
- `docs/domain-model.md`
- `docs/mvp-scope.md`
- `docs/security-and-privacy.md`
- `docs/cloud-portability-contract.md`
- every ADR in `docs/adr/`

If a task conflicts with these documents, stop and ask for direction instead of guessing.

## Stage Discipline

- Work only on the requested stage.
- Preserve behavior outside the requested scope.
- Do not create application code, package files, Docker files, or infrastructure unless the requested stage explicitly includes them.
- Never introduce a cloud SDK before the requested cloud-adapter stage.
- Stage 0 through Stage 12 must complete the local MVP before any cloud SDK is added.
- Stage 13 proves the provider contract.
- OCI may be added only after Stage 13, and only as one adapter and one deployment target.
- AWS and GCP must remain possible future adapters.

## Architecture Boundaries

- Domain and application modules must not import OCI, AWS, GCP, `boto3`, `google-cloud`, or provider SDK packages.
- Domain and application public types must not use provider terms such as PAR, S3 bucket, GCS bucket, OCI namespace, IAM role, or service account.
- Provider-specific code is permitted only under adapters, composition roots, deploy, and infra.
- Persist logical `store_alias` and `object_key`, not signed URLs or permanent provider URLs.
- Use provider-neutral `UploadGrant` and `DownloadGrant` contracts for upload and download access.
- Original files and original metadata are immutable.
- Effective corrected values are stored separately.
- User corrections outrank automation.
- Automated results must include source, confidence, and algorithm version.
- Contributors retain ownership and deletion control over their media.
- Published stories contain sanitized derivatives, never originals.
- Every database change requires an Alembic migration.
- Every authorization rule requires tests.
- Runtime container images must support `linux/amd64` and `linux/arm64`.
- Never commit credentials, generated secrets, access tokens, private keys, or secret values.

## Verification

For code-bearing stages, run the relevant:

- formatter
- linter
- type checks
- tests
- build

Add or update tests whenever behavior changes. If a command cannot run, report why and identify the risk.

For documentation-only stages, review the changed documents for contradictions and confirm that no application code or cloud SDK was added.

## Reporting

At the end of each task, report:

- changed files
- commands run
- command results
- remaining risks or gaps

## Infrastructure Safety

Stop rather than guessing when a destructive infrastructure action, credential, secret, or privileged account is required.

Never run `terraform apply`, cloud deployment commands, database-destructive commands, or an equivalent destructive operation without explicit user approval for that exact action.
