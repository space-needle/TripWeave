# Local MVP Release Checklist

Status legend: `PASS` verified locally, `PARTIAL` implemented with documented gaps, `BLOCKED` requires external setup.

## Product Flow

- `PASS` Owner can register, log in, create a trip, manage settings, and log out.
- `PASS` Owner can create invitation links and revoke invitations.
- `PASS` Guest contributors can join with display names without full accounts.
- `PASS` Owner and guests can upload JPEG/HEIC files through provider-neutral grants.
- `PASS` Worker processes valid media independently from corrupt media.
- `PASS` Reconstruction creates days, stops, moments, routes, and review items.
- `PASS` Review operations are transactional and auditable.
- `PASS` Similarity groups and clock-offset suggestions are created deterministically.
- `PASS` Owner can publish a local immutable story and revoke the share link.
- `PASS` Logged-out viewer can open an unlisted story link until revoked.

## Security And Privacy

- `PASS` Originals remain in `media_private`; public stories use `story_published`.
- `PASS` Public manifests omit raw EXIF, original filenames, private blob refs, and source blob refs.
- `PASS` Session tokens, guest tokens, invitation tokens, and share tokens are stored only as hashes.
- `PASS` CSRF is required for state-changing browser requests.
- `PASS` Auth, invitation creation, upload registration, and publication have local rate limits.
- `PASS` Upload size, file count, MIME type, extension, path traversal, and token-expiration checks are covered.
- `PASS` Cloud SDK markers are absent from lock files.
- `PARTIAL` Published route geometry is photo-inferred and coarse enough for MVP, but exact privacy redaction policy remains a later product decision.

## Operations

- `PASS` `make check` runs format, lint, typecheck, tests, and build.
- `PASS` `make demo` starts the stack and seeds deterministic local data.
- `PASS` `make smoke` checks local health and dependency boundaries.
- `PASS` `make backup-restore-drill` restores a local dump into a temporary database.
- `PASS` `/ops/local-mvp` exposes authenticated job, media, worker, and storage summaries.
- `PASS` API responses propagate `x-request-id`.

## Performance

- `PASS` Story map uses GeoJSON sources and clusters large point sets.
- `PASS` Overview loads thumbnails/previews, not originals.
- `PASS` Worker concurrency is configurable and defaults to 1.
- `PARTIAL` A 300-image generated performance run is documented in `docs/TEST_PLAN.md`; it is not part of `make check` to keep local checks fast.

## Release Candidate Gate

Run:

```sh
make check
make demo
make smoke
make e2e
make backup-restore-drill
```

The local MVP is a release candidate only when every command above passes and `docs/KNOWN_LIMITATIONS.md` contains no critical or high-severity unresolved finding.
