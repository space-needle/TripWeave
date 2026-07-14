# Manual Review Walkthrough

This stage adds review-by-exception corrections for organizers. Original media timestamps,
GPS coordinates, and files remain immutable. Corrections are recorded as `edit_operations`
with before/after values and are applied to effective or generated records.

## Local Walkthrough

1. Start the local stack.

   ```sh
   make dev
   ```

2. Sign in as an owner at `http://localhost:3000`.
3. Create or select a trip.
4. Upload JPEG or HEIC images with a mix of usable GPS, missing GPS, and missing or unusual time metadata.
5. Wait for media to reach `ready`.
6. Run reconstruction.
7. Open the Review inbox in the Reconstruction panel.
8. Review one issue at a time.
9. Use `Resolve` for accepted or corrected issues.
10. Use `Dismiss` for issues that do not require action.
11. Use `Skip` to move to the next open item without changing state.
12. Use `Undo latest edit` after a safe edit to verify the latest reversible correction is undone.
13. Run reconstruction again and confirm user-corrected records remain visible.

## What To Check

- Review counts update as items are resolved or dismissed.
- Each edit creates an `edit_operations` row with meaningful `before_values` and `after_values`.
- Corrected day, stop, moment, route, and media records are marked `user_locked`.
- Reruns replace unlocked automated output but preserve locked corrections.
- Contributors cannot change organizer-only reconstruction structure.
- Original timestamp and GPS columns are not modified by correction operations.

## Supported Edit Operations

- Move media to another moment.
- Move after-midnight media to the previous or next day by changing effective time only.
- Merge stops.
- Split a stop after a selected moment.
- Merge moments.
- Rename day, stop, and moment.
- Move a stop on the map.
- Change route mode/source.
- Exclude media from story.
- Lock corrected records.
- Resolve or dismiss review items.
- Undo the latest safe edit.
