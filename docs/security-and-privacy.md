# Security And Privacy

TripWeave handles personal travel photos, location histories, timestamps, and contributor identities. The product must assume this data is sensitive.

## Core Rules

- Contributors retain ownership and deletion control over their media.
- Original files are private and immutable while retained.
- Original uploads may be retained only temporarily by default to control storage cost and privacy risk.
- Original metadata is private and immutable.
- Published stories contain sanitized derivatives, never originals.
- Persist logical `store_alias` and `object_key`, not signed URLs or permanent provider URLs.
- Never commit credentials or secret values.
- Every authorization rule requires tests.

## Access Model

Trip owners manage trips, invitations, review, and publication. Contributors can upload media and control their own media. Viewers can access only the published story versions or private draft views they are authorized to see.

Authorization must be enforced in backend application services, not only in the web UI. Each authorization rule must have tests for allowed and denied cases.

## Media Privacy

Original media files are never published. For the cloud alpha, originals are processing inputs and are deleted after metadata and display derivatives are generated unless a later retention policy explicitly keeps them. Derivatives must be generated for product display and publication. Derivatives should strip sensitive metadata unless explicitly required for an authorized private workflow.

Published map geometry must be sanitized to avoid exposing exact private movement traces when a less precise path or stop marker is sufficient.

## Deletion And Withdrawal

Contributor deletion control must cover original files, derivatives, metadata visibility, grouping membership, and publication impact. The system must clearly distinguish:

- deleting an unpublished upload
- withdrawing media from future publication
- removing media from already published versions when policy requires it

Any implementation of deletion or takedown must be tested with authorization and publication cases.

## Secrets And Runtime Identity

Secrets must come from local environment configuration, secret stores, or deployment-specific runtime identity mechanisms. They must not be committed.

Domain and application modules must not know whether runtime identity is local credentials, VM identity, workload identity, instance principals, IAM roles, service accounts, or another provider mechanism. Provider-specific identity configuration belongs only in adapters, composition roots, deploy, and infra.

## Provider Isolation

Provider terms and SDKs are prohibited from domain and application modules. Do not expose provider-specific terms in public types, API contracts, or database concepts used by the core product.

Provider-specific deployment permissions must grant only the minimum access needed by the adapter and must be documented in provider-specific deployment docs when those docs are introduced.

## Publication Safety

Publication is a versioned snapshot. A published version must not depend on original private files remaining directly accessible. It must reference sanitized derivatives and sanitized story data.

Publication review should include privacy exceptions for sensitive locations, contributor withdrawal, private metadata leakage, and unexpectedly precise map geometry.
