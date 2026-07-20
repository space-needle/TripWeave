# Test Plan

## Automated Local Gate

```sh
make check
make demo
make smoke
make e2e
make backup-restore-drill
```

## Unit And Integration Coverage

- Authentication lifecycle, session expiration, logout revocation, CSRF.
- Owner trip CRUD and non-leaky cross-user trip access.
- Account-linked invitation acceptance, revocation, expiration, reuse, and trip membership.
- Upload grant creation, duplicate filenames, wrong size, wrong user completion, path traversal, store isolation, token expiration.
- MIME-signature validation, corrupt image failure, decompression-bomb limits, idempotent media processing.
- Reconstruction days, stops, moments, missing GPS, midnight cutoff, repeated place visits, locked edit preservation.
- Edit operations, undo, authorization, stale conflict handling.
- Similarity grouping, representative selection, clock-offset suggestion acceptance/rejection.
- Publication immutability, privacy filtering, repeated publication, revocation, and public asset access.
- Import boundaries and cloud SDK lockfile exclusions.

## Playwright Scenario

`make e2e` covers the browser/API release path:

1. Owner registers.
2. Owner creates a trip.
3. Owner creates two invitations.
4. Two isolated request contexts register contributor accounts and accept invitations.
5. Owner and account contributors upload photos.
6. Worker processes media.
7. Reconstruction creates story structure.
8. Owner publishes locally.
9. Logged-out browser opens the unlisted story.
10. Viewer sees contributor attribution.
11. Owner revokes the share link.
12. Viewer loses access.

The deterministic seed command covers additional fixture variety: three-day trip, two account contributors, EXIF time/GPS, no-GPS media, duplicate media, corrupt media, after-midnight media, and a known-offset camera pattern.

## Manual Performance Drill

Generate or upload 300 lightweight JPEGs, then verify:

- upload registration remains responsive
- worker continues processing with configured concurrency
- `/ops/local-mvp` updates job and media counts
- initial timeline/story load uses thumbnails/previews only
- MapLibre clustering remains enabled
- no obvious N+1 query appears in API logs for media/reconstruction/publication views

## Manual Security Review

- Confirm `.env.example` contains no secrets.
- Confirm lock files contain no OCI, AWS, or GCP SDK.
- Confirm public story API response contains no `media_private`, `sourceBlobRef`, raw EXIF, provider URL, bucket, namespace, or signed URL.
- Confirm contributor-private media is not published.
- Confirm revoked links fail in a logged-out browser.
