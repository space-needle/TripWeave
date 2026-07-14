# Frontend State Model

The primary local trip experience synchronizes one MapLibre map with one chronological timeline.

## Story State

The shared state is intentionally provider-neutral:

- `viewMode`: `TRIP_OVERVIEW`, `DAY`, `STOP`, `MOMENT`, or `PLAYBACK`
- `selectedDayId`
- `selectedStopId`
- `selectedMomentId`
- `selectedMediaId`
- `timeCursor`
- `contributorFilter`
- `mapControlMode`: `STORY_CONTROLLED` or `USER_CONTROLLED`

The map and timeline both read and write this state. Selecting a day, stop, moment, or media item updates the same state object, so map focus and timeline highlight remain synchronized.

## Map Control

`STORY_CONTROLLED` means the map follows the selected story scope. It fits the full trip, selected day, selected stop, selected moment, or playback item.

`USER_CONTROLLED` starts when the user drags the map. In this mode, timeline selection still changes the active story item, but automatic map refitting pauses. The `Follow Story` control returns the map to `STORY_CONTROLLED`.

## Data Model

The frontend converts reconstruction API responses into a `StoryModel`:

- stop points
- media points
- inferred or confirmed route lines
- contributor list
- nearby photo stacks

MapLibre receives GeoJSON sources for stops, media, and routes. Large point sets use source clustering. HTML markers are reserved only for a small selected set, such as the active stop or active moment photos.

## Map Style

`NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL` can point to any MapLibre-compatible style. If it is empty, the app uses a bundled minimal local fallback style with no external tiles. External styles are responsible for correct tile attribution through the MapLibre style metadata.

The product state does not store tile provider names, keys, signed URLs, or provider-specific map objects.

## Responsive Behavior

Desktop uses a side-by-side map and timeline layout. Mobile keeps the map above a scrollable bottom-sheet timeline. The timeline remains keyboard accessible and provides a screen-reader text summary as an alternative to map navigation.

Reduced-motion users receive instant map transitions and non-animated timeline scrolling.

## Future Timezone Work

The local MVP still stores a trip-level `timezone_id`. This is a default for grouping and display, not a final answer for every trip. Multi-timezone travel should be represented later through effective per-day, per-stop, or per-media timezone corrections without mutating original capture metadata.
