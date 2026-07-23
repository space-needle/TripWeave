# Publication And Revocation

Publication creates an immutable local story version from the private trip state.

## Version Model

`story_versions` records one requested publication snapshot. A version moves through
`pending`, `publishing`, `published`, or `failed`. The row records the requested trip,
version number, publication audit fields, manifest BlobRef, source reconstruction run,
and a versioned manifest prefix in `story_published`.

`share_links` records unlisted access. A share token is generated once and only its hash
is stored. A link points at one story version and can be revoked without deleting the
version or private trip data.

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

The logged-out viewer requests `/public/shares/{token}`. The API hashes the token,
checks revocation and expiration, loads the immutable manifest, and returns a read-only
story contract. Asset requests use `/public/shares/{token}/assets/{asset_id}` and are
authorized against the same share token before streaming the `story_published` object
through BlobStore.

The public contract remains provider-neutral: future storage adapters can replace local
streaming with short-lived `DownloadGrant` redirects without changing the manifest
shape.

## Revocation And Unpublish

Revoking a share link marks it revoked and removes future public access through that
URL. Unpublish revokes all active links for the trip and returns the trip visibility to
private. Existing immutable versions remain as audit records; they are inaccessible
without an active share link.

## Limitations

- Publication runs asynchronously through `processing_jobs`; a new link may briefly show
  a publishing state before the worker completes.
- Existing published versions are immutable. Contributor withdrawal affects future
  versions; takedown semantics for already-published versions remain a later policy
  decision.
- Route geometry is the current reconstruction output and is not yet privacy-generalized
  beyond using the story snapshot data.
