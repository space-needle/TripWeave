# Known Limitations

No critical or high-severity local MVP blockers are currently known after the release-candidate checks pass.

## Medium

- Public route geometry is photo-inferred and may reveal approximate stop-to-stop movement. Fine-grained privacy redaction is a later product policy decision.
- Clock-offset suggestions require enough visually similar cross-device matches. Sparse trips may not produce suggestions.
- The local filesystem adapter is intentionally single-node and not a durability substitute for future provider storage.
- HEIC support depends on the installed `pillow-heif` runtime.
- Playwright browsers must be installed locally with `corepack pnpm --dir apps/web exec playwright install chromium`.

## Low

- Published sanitized derivatives are not garbage-collected immediately after revocation.
- The local ops endpoint reports aggregate counts only and does not expose historical trends.
- The 300-image performance drill is manual so ordinary `make check` remains fast.
- Map tiles depend on the configured style URL unless the bundled minimal fallback is used.
