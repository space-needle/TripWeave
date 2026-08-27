# Publication And Revocation

Publication creates an immutable local story version from the private trip state.

## Version Model

`story_versions` records one requested publication snapshot. A version moves through
`pending`, `publishing`, `published`, or `failed`. The row records the requested trip,
version number, publication audit fields, manifest BlobRef, source reconstruction run,
and a versioned manifest prefix in `story_published`.

`share_links` records access to one story version and can be revoked without deleting
the version or private trip data. A published trip receives one stable public slug,
derived from its title plus a short random suffix (for example, `korea-2019-a7f3c9`).
The slug does not change when the trip title changes.

The stable story URL, `/story/{slug}`, resolves to the newest successfully published
version. Every version also has an immutable URL, `/story/{slug}/v/{versionNumber}`.
Creating a new publication updates the stable URL once that version is published; it
never changes an existing version URL. Revoking the newest published version makes the
stable URL unavailable rather than silently falling back to an older version.

## Manifest

The worker builds a JSON manifest under the `story_published` logical store. The
manifest contains presentation data, days, stops, moments, participants, route geometry
and source labels, and public derivative asset BlobRefs.

The manifest does not store local filesystem paths, signed URLs, future provider URLs,
original filenames, raw EXIF, or original BlobRefs. Public API responses may construct
temporary local endpoint URLs from asset IDs, but those URLs are not persisted.

## Asset Publication

Only metadata-stripped thumbnail and preview derivatives are copied into
`story_published`. Originals remain in `media_private` and are never exposed through the
public viewer.

Published manifests are immutable and remain under the story version prefix. Public
derivative objects use checksum-addressed keys scoped to the trip, so repeated
publication versions can reference the same sanitized derivative without creating a new
versioned object for unchanged bytes. The publisher discovers already-copied public
derivatives from previous published manifests rather than probing object storage for
each asset.

Publishability v1 requires:

- a successful reconstruction run
- at least one READY media item
- `include_in_story = true`
- `visibility = story`
- metadata-stripped thumbnail and preview assets
- media assigned into the reconstruction outline

Contributor restrictions are respected because publication only includes media whose
contributor-visible state permits story publication. Owner/editor include decisions do
not publish media that remains private or trip-members-only.

## Public Access

The logged-out viewer requests `/public/stories/{slug}` for the latest published story
or `/public/stories/{slug}/versions/{versionNumber}` for a fixed version. Asset requests
always include the resolved version and are authorized against that version's share-link
record before streaming the `story_published` object through BlobStore. These are public
identifiers, not secrets; the privacy boundary is the sanitized publication snapshot and
its revocation state. Legacy token URLs remain available for existing links during the
migration.

The public contract remains provider-neutral: future storage adapters can replace local
streaming with short-lived `DownloadGrant` redirects without changing the manifest
shape.

## Revocation And Unpublish

Revoking a share link marks that version revoked and removes future public access through
its version URL. If it is the newest successfully published version, the stable URL also
becomes unavailable. Unpublish revokes all active links for the trip and returns the trip
visibility to private. Existing immutable versions remain as audit records; they are
inaccessible without an active share link.

## Limitations

- Publication runs asynchronously through `processing_jobs`; a new link may briefly show
  a publishing state before the worker completes.
- Existing published versions are immutable. Contributor withdrawal affects future
  versions; takedown semantics for already-published versions remain a later policy
  decision.
- Route geometry is the current reconstruction output and is not yet privacy-generalized
  beyond using the story snapshot data.
