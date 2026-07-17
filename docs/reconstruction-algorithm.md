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

The backend defines a provider-neutral `Geocoder` port with reverse-geocoding semantics. The local adapter does not call an external service. By default it returns no place name, but tests and local fixtures may register manual coordinate-to-name entries.

When reverse geocoding returns a name, reconstruction uses it as the generated place name and initial stop title. These names are automated output with source, confidence, and algorithm version recorded through the generated reconstruction record. User-edited stop names remain `user_locked` corrections and must not be overwritten by reruns.

## Incremental Updates And Locked Records

The first reconstruction creates a full generated story. Later story updates are incremental when a visible story already exists:

- Existing days, stops, moments, media assignments, and user-corrected names are carried forward into the new run.
- READY media already assigned to a moment is not moved automatically.
- New READY media is assigned to an existing stop when its effective day, location, and capture time fit the stop radius and time-gap rules.
- New READY media that does not fit an existing stop creates a new stop and moment in chronological order.
- Missing or unusable metadata creates review items instead of guessing.
- Inferred legs for affected days are rebuilt between consecutive stops while user-locked corrections are preserved.

User-corrected records remain `user_locked` and must not be overwritten by reruns or incremental updates.
