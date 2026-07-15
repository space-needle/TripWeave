# Privacy Model

TripWeave treats travel photos, locations, timestamps, contributors, and publication links as sensitive data.

## Private Originals

Uploaded originals are immutable and stored in the `media_private` logical store. PostgreSQL stores logical blob refs, checksums, sizes, and metadata facts, never file bytes or durable signed URLs.

Raw EXIF and XMP metadata are used only for authenticated private workflows. Derivatives strip unnecessary metadata.

## Contributor Control

Contributors retain authorship and control over their own media. Owners can include publishable media but cannot override contributor private restrictions.

Visibility states:

- `private`: contributor restricted; not publishable.
- `trip`: visible to trip members only.
- `story`: eligible for publication.
- `excluded`: deliberately omitted from story workflows.

## Publication

Publication creates an immutable story version containing sanitized manifest data and sanitized derivative blobs in `story_published`.

Public stories never expose:

- originals
- raw EXIF or XMP
- private store refs
- source blob refs
- session, invitation, upload, or share token hashes

Unlisted share tokens are random and stored only as hashes. Revocation denies future public access.

## Local Operations

The local ops endpoint is authenticated and returns aggregate counts only. It is intended for local release checks, not public administration.
