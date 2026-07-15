# Collaboration Intelligence

TripWeave groups similar contributed photos and suggests device clock offsets without
deleting originals or mutating original metadata.

## Similarity Groups

`similarity_groups` and `similarity_group_members` are generated during
reconstruction. Groups are scoped to one trip.

The first pass groups exact duplicates by SHA-256. The second pass groups visually
similar media using an 8x8 average perceptual hash, bounded by compatible trip,
time, and location evidence. Originals remain intact, and grouped media stays
visible as separate versions.

The recommended representative is explainable. The first version scores:

- resolution
- sharpness estimate from luminance variance
- exposure clipping
- orientation
- contributor favorite, currently reserved for a later UI signal

Users may choose another representative. That operation locks the generated group
instead of deleting or rewriting member media.

## Device Clock Offset Suggestions

`capture_devices` stores a provider-neutral local grouping key derived from trip,
contributor, and safe camera hints. `device_clock_offset_suggestions` records
automated offset evidence separately from original metadata.

The algorithm finds strong cross-device matches by perceptual similarity and
compatible location. It calculates timestamp deltas, requires at least three
supporting matches, uses the median offset, and records median absolute deviation
as robust dispersion.

Suggestions are routed through review as `possible_clock_offset`. Accepting a
suggestion stores the accepted offset on the capture device, updates only
`effective_captured_at_utc` for affected media, and queues reconstruction. Original
timestamps remain unchanged.

## Limitations

- The perceptual hash is intentionally simple and local; it is not a forensic
  duplicate detector.
- Similar scenes at different moments are bounded by time/location, but false
  positives remain possible.
- Clock-offset suggestions require repeated supporting matches and will not infer
  offsets from a single pair.
- HEIC/JPEG decoding quality depends on local codec support.
- No facial recognition, emotion detection, identity inference, or biometric
  grouping is implemented.
- Contributor favorites are modeled as a future scoring signal but are not exposed
  in this stage.
