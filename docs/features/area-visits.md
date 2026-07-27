# AreaVisit

## 1. Purpose

TripWeave currently organizes a trip using the following structure:

```text
Trip
└── Day
    └── Stop
        └── Moment
            └── Media
```

This structure works well when a Day contains only a small number of Stops.

However, when a Day contains dozens of Stops and many of them are concentrated in the same geographic area, several problems appear:

* Map markers overlap.
* The visit sequence becomes difficult to read.
* The full-day route becomes visually cluttered.
* Users must navigate through dozens of Stops one by one.
* A single visit experience, such as a campus, park, or waterfront walk, appears fragmented across many Stops.

To address this, TripWeave should add an optional `AreaVisit` layer between `Day` and `Stop`.

```text
Trip
└── Day
    ├── AreaVisit
    │   ├── Stop
    │   │   └── Moment
    │   │       └── Media
    │   ├── Stop
    │   └── Stop
    │
    ├── Standalone Stop
    │
    └── AreaVisit
        ├── Stop
        └── Stop
```

An `AreaVisit` does not replace an existing Stop.

> A Stop represents a detailed visit fact. An AreaVisit groups multiple spatially and temporally continuous Stops into one understandable visit segment.

---

## 2. Core Decision

### Do not change the existing Stop-generation logic

AreaVisit grouping is a post-processing step that runs after Stops have already been generated.

```text
Media processing
    ↓
Day generation
    ↓
Stop generation
    ↓
Moment generation
    ↓
AreaVisit grouping
    ↓
Review and presentation
```

AreaVisit generation must not modify:

* Stop IDs
* Stop locations
* Stop start or end times
* Stop order
* Moments linked to Stops
* Media linked to Stops
* Stop notes
* Stop participants
* The existing Stop-generation algorithm

If AreaVisit generation fails or is disabled, the existing Stop-based trip experience must continue to work normally.

---

## 3. Terminology

### Place

A persistent physical location.

Examples:

```text
University of Washington
Seattle Waterfront
Green Lake
```

### AreaVisit

A visit event that occurred at a specific place during a specific time period.

Example:

```text
2026-06-26 10:20–12:05
Visit to the University of Washington
```

If the same physical place is visited in the morning and again in the evening, those visits should become separate AreaVisits.

```text
Place
└── University of Washington

AreaVisit 1
└── Morning campus visit

AreaVisit 2
└── Evening campus revisit
```

### MapCluster

A rendering feature that temporarily groups overlapping markers based on the current zoom level and viewport.

```text
AreaVisit
- Product and story structure
- Uses both time and space
- Persisted in the database
- Shared by map and timeline views

MapCluster
- Prevents visual marker overlap
- Changes with zoom level
- Not persisted in the database
- Used only for map rendering
```

AreaVisit and MapCluster are separate concepts and may be used together.

---

## 4. AreaVisit Generation Principles

### Optional hierarchy

Not every Stop must belong to an AreaVisit.

```text
Three or more nearby consecutive Stops
→ AreaVisit candidate

A single restaurant visit
→ Standalone Stop

A Day containing only two Stops
→ No AreaVisit required
```

### Created only within the same Day

Stops from different Days must never be grouped into the same AreaVisit.

### Only chronologically contiguous Stops may be grouped

Stops inside an AreaVisit must be consecutive according to the existing `sort_order` or effective chronological order.

Do not skip unrelated visits and group only spatially nearby Stops.

Example:

```text
10:00 UW Campus
12:00 Downtown
15:00 Waterfront
19:00 UW Campus
```

Expected result:

```text
AreaVisit 1 · UW Campus morning
AreaVisit 2 · Downtown
AreaVisit 3 · Waterfront
AreaVisit 4 · UW Campus evening
```

### User edits take precedence

When a user edits an AreaVisit, that result must be preserved during later automatic regeneration.

```text
source = user_edited
user_locked = true
```

### Deleting an AreaVisit must not delete Stops

```text
Delete AreaVisit
→ Remove only the grouping
→ Preserve Stops, Moments, and Media
```

---

## 5. AreaVisit Membership Evaluation

When deciding whether a new Stop, `candidate`, should be added to the current Area candidate, `area`, calculate the following metrics.

### 5.1 Distance from the immediately previous Stop

```text
d_prev = distance(previous_stop, candidate)
```

Purpose:

* Determine whether movement continues naturally from the previous Stop
* Separate a geographically distant next visit

Example:

```text
UW Main Gate
→ 120 m
Red Square
→ 180 m
Suzzallo Library
```

Using only `d_prev` can create a chaining problem, where each Stop is close to the previous one but the Area gradually grows across several kilometers.

---

### 5.2 Distance from the current Area center

```text
d_center = distance(area_center, candidate)
```

Purpose:

* Prevent the Area from drifting along with each new Stop
* Determine whether the candidate still belongs to the Area’s central region

Prefer a `medoid` over a simple arithmetic coordinate average.

```text
medoid =
The Stop in the Area with the smallest total distance to all other Stops
```

Advantages:

* The center corresponds to a real Stop
* More resistant to GPS outliers
* Computationally inexpensive for small Stop collections

---

### 5.3 Maximum distance from existing Area members

```text
d_farthest =
max(distance(candidate, each_existing_area_stop))
```

Purpose:

* Detect whether the candidate is too far from one or more existing members
* Prevent overly broad groupings that may still appear close to the center

---

### 5.4 Resulting Area diameter after adding the candidate

```text
new_diameter =
max(distance(stop_i, stop_j))
```

Purpose:

* Prevent the two ends of an Area from becoming too far apart
* Prevent chaining from creating an Area that spans several kilometers

---

### 5.5 Time gap from the previous Stop

```text
time_gap =
candidate.start_time - previous_stop.end_time
```

Purpose:

* Separate morning and evening visits to the same place
* Treat a visit after a long break as a new AreaVisit

---

### 5.6 Stop-order continuity

```text
candidate.sort_order == previous_stop.sort_order + 1
```

Or use an equivalent continuity rule that matches the existing project’s Stop-order semantics.

Purpose:

* Prevent spatially nearby Stops from being grouped while skipping intervening visits

---

### 5.7 Location confidence

A Stop with low-confidence location data should not incorrectly create an Area boundary.

Initial policy:

```text
High-confidence location
→ Use normally for distance evaluation

Low-confidence location
→ Consider neighboring Stops and temporal context
→ Do not use as the primary Area-boundary signal
→ Create a review item when appropriate
```

---

## 6. Basic Area Membership Rule

The initial version should use explicit hard rules rather than machine learning.

```python
can_join_area = (
    is_contiguous
    and time_gap <= MAX_TIME_GAP
    and d_prev <= MAX_PREVIOUS_DISTANCE
    and d_center <= MAX_CENTER_DISTANCE
    and new_diameter <= MAX_AREA_DIAMETER
)
```

Initial experimental defaults:

```text
MIN_AREA_STOPS = 3

MAX_PREVIOUS_DISTANCE_METERS = 400
MAX_CENTER_DISTANCE_METERS = 700
MAX_AREA_DIAMETER_METERS = 1200
MAX_TIME_GAP_MINUTES = 45

ALGORITHM_VERSION = "area_visit_v1"
```

These values are starting points for testing against real examples such as Seattle and the University of Washington campus. They are not permanent product constants.

Role of each metric:

| Metric         | Purpose                                  |
| -------------- | ---------------------------------------- |
| `d_prev`       | Continuity with the previous visit       |
| `d_center`     | Cohesion around the Area center          |
| `d_farthest`   | Maximum separation from existing members |
| `new_diameter` | Maximum overall Area size                |
| `time_gap`     | Temporal continuity                      |
| `sort_order`   | Preservation of trip sequence            |

---

## 7. AreaVisit Seed Conditions

Do not create an AreaVisit from only two nearby Stops.

By default, use three consecutive Stops as the seed.

```text
Stop A
Stop B
Stop C
```

The seed is valid when:

```text
A → B passes distance and time conditions
B → C passes distance and time conditions
A/B/C pass the maximum-diameter condition
The Stop order is contiguous
```

After the seed is created, evaluate additional Stops one at a time.

```text
[A, B, C]
    + D
    + E
    + F
```

When a candidate Stop fails a hard condition, finalize the current AreaVisit.

Stops that do not meet the minimum Area size remain Standalone Stops.

---

## 8. Algorithm Overview

```python
def group_area_visits(
    stops: list[StopInput],
    config: AreaVisitConfig,
) -> AreaGroupingResult:
    ordered_stops = sort_stops(stops)

    results = []
    index = 0

    while index < len(ordered_stops):
        seed = ordered_stops[
            index : index + config.min_area_stops
        ]

        if not valid_seed(seed, config):
            results.append(
                StandaloneStopResult(
                    stop_id=ordered_stops[index].id
                )
            )
            index += 1
            continue

        area = AreaCandidate.from_seed(seed)
        index += config.min_area_stops

        while index < len(ordered_stops):
            candidate = ordered_stops[index]
            previous = area.stops[-1]

            metrics = calculate_candidate_metrics(
                area=area,
                previous=previous,
                candidate=candidate,
                config=config,
            )

            if can_join_area(metrics, config):
                area.add(candidate)
                area.recalculate_center()
                index += 1
            else:
                break

        results.append(area.finalize())

    return refine_grouping(results, config)
```

Required characteristics:

* Identical input and configuration must produce identical output.
* Input Stops must not be mutated.
* The grouping logic must be independent from the database and cloud providers.
* The algorithm must remain separate from existing Stop-generation code.
* AreaVisit grouping failure must not fail the entire trip reconstruction.

---

## 9. Optional Refinement Pass

After the first sequential grouping pass, an optional refinement pass may be performed.

### Merge adjacent AreaVisits

Two consecutive AreaVisits may be merged if the combined result still satisfies all limits.

```text
combined_time_gap <= MAX_TIME_GAP
combined_diameter <= MAX_AREA_DIAMETER
combined center distance remains within limits
```

### Split an oversized AreaVisit

Find the largest spatial or temporal break inside an Area.

```text
Stop 1 → 120 m
Stop 2 → 160 m
Stop 3 → 1100 m
Stop 4 → 90 m
Stop 5
```

The boundary between Stop 3 and Stop 4 may be a split candidate.

Possible split signals:

* Large spatial gap
* Long time gap
* High implied travel speed
* Change in neighborhood or parent place
* Participant route divergence

Version 1 should keep refinement minimal and first validate the basic sequential grouping behavior.

---

## 10. Compact and Corridor Shapes

Not every AreaVisit is spatially compact.

### Compact Area

A campus, museum complex, shopping center, or park where Stops are distributed around a center.

```text
    ②
 ①  ●  ③
    ④
```

### Corridor Area

A waterfront, walking route, or hiking trail where Stops form a linear sequence.

```text
① ─ ② ─ ③ ─ ④ ─ ⑤
```

For corridor-shaped visits, `d_prev` may remain small while `d_center` and `new_diameter` become large.

Version 1 does not need to classify Area shape explicitly.

After validation with real data, the following may be added if necessary:

```text
area_shape = compact | corridor
```

---

## 11. AreaVisit Naming

Version 1 should not use AI-generated names.

Suggested naming priority:

```text
1. Shared parent POI among included Stops
   → University of Washington

2. Shared neighborhood or district
   → Belltown

3. Parent location of the representative Stop
   → Seattle Waterfront

4. Low-confidence fallback
   → Area 3
   → Nearby stops
   → Request user confirmation
```

Automatically generated names are suggestions and must be editable.

The user interface should display the actual place name rather than technical terms such as `AreaVisit` or `Cluster`.

---

## 12. Data Model

### `area_visits`

```text
area_visits
- id
- trip_day_id
- reconstruction_run_id
- place_id nullable
- title
- start_time
- end_time
- center
- bounds
- cover_media_id nullable
- source
- confidence
- algorithm_version
- sort_order
- user_locked
- created_at
- updated_at
```

### `area_visit_stops`

```text
area_visit_stops
- area_visit_id
- stop_id
- sort_order
- membership_source
- confidence
- user_locked
- created_at
- updated_at
```

Within one reconstruction result, a Stop may belong to at most one AreaVisit.

```text
UNIQUE(reconstruction_run_id, stop_id)
```

Reasons for using a join table:

* Minimize changes to the existing Stop model
* Store membership source and confidence independently
* Distinguish automatic results from user edits
* Represent moving a Stop between Areas
* Preserve regeneration history
* Support user locking

---

## 13. Automatic-Generation Metadata

Automatically generated AreaVisits and memberships should record:

```text
source
confidence
algorithm_version
reconstruction_run_id
user_locked
```

Example:

```text
source = auto_grouped
confidence = 0.91
algorithm_version = area_visit_v1
user_locked = false
```

After a user edit:

```text
source = user_edited
user_locked = true
```

---

## 14. Decision Diagnostics

The AreaVisit algorithm will need tuning against real travel data, so every membership decision should be explainable.

Accepted candidate example:

```json
{
  "candidate_stop_id": "stop-26",
  "previous_distance_m": 184,
  "center_distance_m": 392,
  "farthest_member_distance_m": 711,
  "new_area_diameter_m": 834,
  "time_gap_seconds": 780,
  "location_confidence": 0.94,
  "accepted": true,
  "rejection_reason": null,
  "algorithm_version": "area_visit_v1"
}
```

Rejected candidate example:

```json
{
  "candidate_stop_id": "stop-27",
  "previous_distance_m": 3620,
  "center_distance_m": 4102,
  "farthest_member_distance_m": 4480,
  "new_area_diameter_m": 4480,
  "time_gap_seconds": 1200,
  "location_confidence": 0.98,
  "accepted": false,
  "rejection_reason": "PREVIOUS_DISTANCE_EXCEEDED",
  "algorithm_version": "area_visit_v1"
}
```

Supported rejection reasons:

```text
PREVIOUS_DISTANCE_EXCEEDED
CENTER_DISTANCE_EXCEEDED
AREA_DIAMETER_EXCEEDED
TIME_GAP_EXCEEDED
LOW_LOCATION_CONFIDENCE
INVALID_OR_MISSING_LOCATION
NON_CONTIGUOUS_STOP_ORDER
```

Diagnostics are primarily for development, testing, tuning, and review-item generation. They do not need to be shown directly to end users.

---

## 15. Confidence Calculation

Confidence may be calculated using each metric’s ratio to its configured limit.

```text
previous_ratio = d_prev / MAX_PREVIOUS_DISTANCE
center_ratio = d_center / MAX_CENTER_DISTANCE
diameter_ratio = new_diameter / MAX_AREA_DIAMETER
time_ratio = time_gap / MAX_TIME_GAP
```

Initial example policy:

```text
All ratios < 0.6
→ high confidence

One or more ratios between 0.6 and 0.9
→ medium confidence

One or more ratios >= 0.9
→ low confidence
```

Do not ask users to review every generated AreaVisit.

Only low-confidence results should enter the review queue.

Example:

```text
We grouped 8 Stops into a UW Campus visit.

[Confirm]
[View Stops]
[Split]
```

---

## 16. User Editing

AreaVisit may eventually support:

* Rename AreaVisit
* Change representative photo
* Merge two AreaVisits
* Split one AreaVisit into two
* Move a Stop to another AreaVisit
* Add a Standalone Stop to an AreaVisit
* Remove a Stop from an AreaVisit
* Delete an AreaVisit
* Reorder AreaVisits
* Prevent automatic regeneration

The first implementation may begin with read-only AreaVisits and defer editing until a later phase.

---

## 17. Map UI

### Day Overview

The Day-level map should display only:

* AreaVisits
* Standalone Stops

Do not display all individual Stops when the Day is highly dense.

```text
6/26 Seattle

① Belltown
② Downtown
③ UW Campus
④ Green Lake
⑤ Capitol Hill
```

AreaVisit markers may include:

```text
Representative photo
Area visit order
Area name
Stop count
```

Example:

```text
┌────────────┐
│ Cover photo│ ③
└────────────┘
UW Campus
8 stops
```

The Day Overview should use a simplified route connecting AreaVisits rather than rendering every Stop-level segment.

```text
Belltown
   ↓
Downtown
   ↓
UW Campus
   ↓
Green Lake
```

---

### Area View

When the user selects `UW Campus`:

1. Fit the map to the Area bounds.
2. Hide the Area marker.
3. Display Stops inside the Area.
4. Display the internal Stop-level route.
5. Update the bottom card with Area details.

Example:

```text
6/26 › UW Campus

10:20–12:05
8 stops · 31 photos · 3 travelers
```

Navigation inside the Area:

```text
Stop 3 of 8
```

Optional secondary information:

```text
Overall stop 19 of 52
```

---

### Stop View

After selecting a Stop, reuse the existing Stop View.

```text
Suzzallo Library
10:48–11:12

7 photos · 3 travelers
Stop 3 of 8
```

Navigation hierarchy:

```text
6/26 › UW Campus › Suzzallo Library
```

Back navigation:

```text
Stop View
→ Area View
→ Day Overview
```

The previous map bounds and selection state should be restored when navigating back.

---

## 18. Map Zoom and Story State

Pinch-zooming alone should not automatically switch from Day View to Area View.

Recommended behavior:

```text
Map zoom
→ Adjust marker presentation only

Tap Area marker
→ Enter Area View

When sufficiently zoomed in
→ Optionally show a "View 8 stops" action
```

Map-camera state and story-navigation state should remain separate.

When an Area is selected, the Area marker may transition into its individual Stops.

```text
[UW Campus · 8 stops]
           ↓
① ② ③ ④ ⑤ ⑥ ⑦ ⑧
```

---

## 19. Timeline UI

AreaVisit must also be represented in the Timeline, not only on the map.

```text
6/26 Seattle

09:00–10:10
Belltown
  ├── Hotel
  ├── Cafe
  └── Sculpture Park

10:40–13:00
Downtown
  ├── Pike Place Market
  ├── Waterfront
  └── Seattle Art Museum

14:00–17:00
UW Campus
  ├── Main Gate
  ├── Red Square
  ├── Suzzallo Library
  └── Drumheller Fountain
```

AreaVisit sections may be collapsible.

The map and timeline should share the same application state.

```text
selectedDayId
selectedAreaVisitId
selectedStopId
selectedMomentId
```

---

## 20. API Response Direction

The Day-detail response should provide both AreaVisits and Standalone Stops.

Example:

```json
{
  "day": {
    "id": "day-1",
    "date": "2026-06-26"
  },
  "area_visits": [
    {
      "id": "area-uw",
      "title": "UW Campus",
      "start_time": "2026-06-26T10:20:00",
      "end_time": "2026-06-26T12:05:00",
      "stop_count": 8,
      "photo_count": 31,
      "traveler_count": 3,
      "bounds": {},
      "center": {},
      "cover_media": {}
    }
  ],
  "standalone_stops": []
}
```

Existing Stop APIs should remain unchanged.

The AreaVisit-detail endpoint should return included Stops in their existing order.

---

## 21. Story-Version Compatibility

Existing published Story Versions may not include AreaVisit data.

New manifests should add AreaVisit fields as optional.

```json
{
  "days": [
    {
      "area_visits": [],
      "standalone_stops": []
    }
  ]
}
```

Compatibility rules:

```text
Existing Story Version
→ No AreaVisit data
→ Render using the existing Stop-based experience

New Story Version
→ Use AreaVisit rendering when AreaVisits exist
→ Fall back to Stop-based rendering when they do not
```

Existing published versions must not be rewritten solely to add AreaVisit support.

---

## 22. Implementation Phases

### Phase 1 — Algorithm Dry Run

Scope:

* Pure deterministic grouping function
* Versioned configuration
* Decision diagnostics
* Read-only preview command
* Validation against existing Stop data

Out of scope:

* Database changes
* API changes
* Frontend changes
* Story-manifest changes
* Area editing

Example command:

```text
area-visits preview --trip-id <id> --day-id <id>
```

Output should include:

* Existing Stop count
* Proposed AreaVisit count
* Standalone Stop count
* Stop list for each AreaVisit
* Area time range
* Area maximum diameter
* Decision diagnostics
* Rejection reasons
* Active configuration values

---

### Phase 2 — Data Model and Persistence

Scope:

* `area_visits`
* `area_visit_stops`
* Alembic migration
* Area-grouping job
* Idempotent persistence
* Algorithm version
* Confidence
* Diagnostic storage

Out of scope:

* Frontend changes
* Manual editing
* Story-manifest changes

---

### Phase 3 — Read APIs

Scope:

* AreaVisits for a Day
* Standalone Stops for a Day
* AreaVisit details
* Included Stop list
* Bounds
* Center
* Representative image
* Area-grouping status

---

### Phase 4 — Day Overview and Drill-In

Scope:

* Display AreaVisits in Day Overview
* Display Standalone Stops
* Simplified Area-level route
* Area selection
* Fit map to Area bounds
* Display Stops inside the selected Area
* Reuse existing Stop View
* Breadcrumb navigation
* Restore previous map state on back navigation

---

### Phase 5 — Timeline Integration

Scope:

* AreaVisit timeline sections
* Expand and collapse behavior
* Map and Timeline selection synchronization
* Stop navigation inside an Area

---

### Phase 6 — Editing and Review

Scope:

* Rename AreaVisit
* Merge AreaVisits
* Split AreaVisit
* Move Stop between AreaVisits
* Add Standalone Stop to AreaVisit
* Delete AreaVisit
* Change representative photo
* User locking
* Review low-confidence AreaVisits

---

### Phase 7 — Story-Version Support

Scope:

* Add AreaVisit data to new manifests
* Preserve fallback for older manifests
* Public-viewer Area drill-in
* Preserve snapshot immutability

---

## 23. Test Scenarios

### Nearby sequential Stops

```text
5 Stops
Adjacent distances: 50–200 m
Time gaps: 5–15 minutes
Overall diameter: 600 m

Expected:
1 AreaVisit
```

### Only two Stops

```text
2 nearby Stops

Expected:
Both remain Standalone Stops
```

### Distant next Stop

```text
Last Stop in current Area
→ Next Stop is 4 km away

Expected:
Current Area ends
Next Stop starts a new candidate or remains standalone
```

### Chaining prevention

```text
Every adjacent Stop is 200 m apart
Overall diameter is 2.5 km

Expected:
Split based on MAX_AREA_DIAMETER
```

### Large time gap

```text
Same location
5-hour time gap

Expected:
Separate AreaVisits
```

### Revisiting the same place

```text
Morning at UW Campus
Afternoon Downtown
Evening at UW Campus

Expected:
2 separate UW Campus AreaVisits
```

### Stop without location

```text
Previous and next Stops belong to the same Area
Middle Stop has no location
Time gaps are small

Expected:
No crash
Either include with low confidence or leave standalone/create review item
```

### Preserve user edits

```text
User splits one AreaVisit into two
Area grouping runs again

Expected:
User-edited structure is preserved
```

### Existing Story Version

```text
Load a Story Version without AreaVisit data

Expected:
Existing Stop-based UI renders normally
```

---

## 24. Completion Criteria

For the Seattle example:

```text
✓ All existing 52 Stops still exist.
✓ Stop times, locations, Moments, and Media remain unchanged.
✓ Day Overview displays only AreaVisits and Standalone Stops.
✓ UW Campus appears as one AreaVisit.
✓ Selecting UW Campus drills into its internal Stops.
✓ Existing Stop order is preserved inside the Area.
✓ Deleting an Area does not delete Stops or Media.
✓ Days without AreaVisits continue using the existing Stop UI.
✓ Revisits to the same place create separate AreaVisits.
✓ Chaining does not create excessively large Areas.
✓ User-edited Areas survive regeneration.
✓ Map and Timeline use the same AreaVisit structure.
✓ Existing Story Versions continue working without AreaVisit data.
✓ Every automatic decision records an algorithm version and diagnostics.
```

---

## 25. Prohibited Implementation Changes

* Do not change the existing Stop-generation algorithm.
* Do not automatically merge or delete Stops.
* Do not replace AreaVisit with generic map clustering.
* Do not determine Area membership from zoom level.
* Do not group non-contiguous Stops into the same AreaVisit.
* Do not overwrite user-edited Areas during regeneration.
* Do not require AI-generated Area names in version 1.
* Do not fail the full reconstruction when AreaVisit grouping fails.
* Do not force migration of existing Story Versions.
* Do not couple AreaVisit domain logic to any cloud provider.

---

## 26. Final Definition

> An AreaVisit is an optional parent layer that groups chronologically contiguous and spatially cohesive Stops from the same Day into one visit segment.

AreaVisit membership should consider at least:

```text
Distance from the previous Stop
Distance from the current Area center
Maximum distance from existing Area members
Resulting Area diameter
Time gap from the previous Stop
Stop-order continuity
Location confidence
```

Final navigation structure:

```text
Day Overview
→ AreaVisit or Standalone Stop

Area View
→ Stops inside the AreaVisit

Stop View
→ Existing Stop details, Moments, and Media
```

AreaVisit does not replace Stop.

> Existing Stops remain the detailed facts of the trip. AreaVisit groups those Stops into a regional visit experience that is easier for people to understand and explore.
