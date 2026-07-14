# Reconstruction Algorithm

TripWeave reconstruction v1 is deterministic, local, and provider-neutral.

## Version

- `algorithm_version`: `reconstruction_v1`
- Stop radius: 150 meters
- Stop time gap: 60 minutes
- Moment time gap: 15 minutes
- Missing GPS bracket window: 30 minutes
- Maximum implied travel speed: 160 km/h

These values are persisted on each `reconstruction_runs.algorithm_config` record.

## Inputs

The algorithm reads `media_items` for one trip where:

- `processing_state = ready`
- `deleted_at IS NULL`

It never overwrites original capture metadata. It uses `effective_captured_at_utc` when present, otherwise `original_captured_at_utc`. It uses `effective_location`; missing location is handled by the review-by-exception rules below.

## Days

The algorithm resolves each usable media item into an effective trip day:

1. If `original_utc_offset_minutes` exists, apply that offset to the UTC timestamp.
2. Otherwise use the trip timezone.
3. If the timezone is invalid, fall back to UTC.
4. Subtract `trips.day_cutoff_hour`, default 4, before taking the local date.

Media with unusable time creates an `unknown_time` review item instead of being guessed into a day.

## Stops And Places

Media is processed chronologically within each effective day. A new stop starts when any of these is true:

- distance from the current stop centroid exceeds 150 meters
- gap from the previous media exceeds 60 minutes
- implied speed from the previous media exceeds 160 km/h

A place is persistent within a run. A stop is one visit. Returning to the same place after a substantial interval creates a new stop that may reuse the same place.

Parallel contributor paths are not forced into one stop. If contributors are taking photos at substantially different places at the same time, distance and speed rules split the stops.

## Moments

Moments split each stop using the tighter 15-minute time gap. Moment media keeps all perspectives, and `moment_participants` records each contributor represented in the moment.

## Missing GPS

Missing GPS is assigned only when the media is tightly bracketed in time by high-confidence GPS media already assigned to the same stop. Otherwise the algorithm creates an `unknown_location` review item.

## Routes

The algorithm creates legs between consecutive stops in the same day. Initial geometry is straight-line geography and `route_source = photo_inferred`. No directions or external map provider is used.

## Geocoding

The backend defines a provider-neutral `Geocoder` port. The local adapter is a no-op/manual adapter, so place names may remain blank until manually entered later.

## Reruns And Locked Records

Reruns create a new `reconstruction_runs` record. Generated records with `user_locked = false` are replaced. Records with `user_locked = true` are preserved so future correction workflows can protect human edits.
