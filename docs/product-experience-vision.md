# TripWeave Product Experience Vision

TripWeave is a shared travel story workspace. It helps families, friends, and
travel groups combine photos from many people into one evolving story with a
map, timeline, notes, contributors, and eventually searchable memories across
years of trips.

The current product already supports the foundation for this: an owner can
create a trip, invite contributors, collect photos, process media locally,
review reconstructed trip structure, and publish a sanitized public story. The
next product direction should shift the center of gravity from one owner
publishing a finished artifact to a group of account members building and
revisiting shared stories together.

## Product Promise

TripWeave turns scattered camera rolls into shared travel memories.

After a trip, each traveler can add their photos. TripWeave aligns timestamps
and locations, groups media into days, stops, and moments, and builds an
interactive story that everyone in the group can explore. Over time, each user
builds a personal library of trips they created, joined, appeared in, or helped
document.

## Current Local MVP Behavior

The current app is local-first and cloud-agnostic. It runs with a Next.js web
app, FastAPI backend, PostgreSQL/PostGIS database, worker, local filesystem blob
storage, and Docker Compose.

Current core capabilities include:

- Account registration and login for trip owners.
- Owner-created trips with title, dates, timezone, and settings.
- Contributor invite links.
- Contributors accept invite links after logging in or creating an account.
- Account-linked contributors can upload photos and return to joined trips from
  their trip library.
- Uploads are stored through provider-neutral blob references.
- Original files are private processing inputs, immutable while retained, and may be deleted after optimized story derivatives and metadata are created.
- Media processing extracts thumbnails, previews, timestamps, location data, and
  processing state.
- Trips can be reconstructed into days, stops, moments, routes, and review
  items.
- Owner/editor review workflows can correct trip structure and metadata.
- Owners can publish sanitized story snapshots.
- Public share links allow logged-out viewers to see published story versions.
- Published stories use derivatives and sanitized story data, not originals.

This current flow is useful, but it still feels close to an owner collecting
submissions and publishing a final album.

## Product Direction

The stronger long-term product is a shared story workspace.

In this model, a trip is not only something one owner publishes. It is a private
group memory space where members can add photos, write notes, correct context,
revisit the story, and later search across all trips they are connected to.

Publication remains useful, but it becomes an external sharing action rather
than the main product experience. The main experience is the authenticated story
library and shared trip workspace.

## Primary User Experience

### Story Library

When a user logs in, they should see every story they are connected to, not only
the trips they own.

This includes:

- Trips they created.
- Trips where they are an editor, contributor, or viewer.
- Trips they joined from an invitation link.
- Trips shared privately by family or friends.

The library should support both list and map views. Over time, it becomes the
user's travel memory archive.

### Shared Story Workspace

Opening a story should show a collaborative workspace:

- Map and timeline synchronized around days, stops, moments, and media.
- Photo uploads from all authorized members.
- Contributor attribution.
- Notes or comments on days, stops, moments, and individual photos.
- Review items for missing time, missing location, likely clock offsets, and
  grouping issues.
- Visibility controls for private, trip-member-only, story-visible, and public
  publication states.

The workspace should feel like a living shared story, not only a staging area
for publication.

### Contributor Flow

Invite links should start with an account-linked path:

- Open invite link.
- Log in or create an account.
- Join the story as an account member.
- Upload photos.
- See the story later from the user's own story library.

A low-friction guest upload path can be reconsidered later, but it should not
be the V0 default because guest uploads need a separate claim and recovery
model.

## Roles And Permissions

The product should distinguish private collaboration from public sharing.

Recommended member roles:

- `owner`: creates the trip, manages members, deletes the trip, publishes and
  unpublishes story snapshots.
- `editor`: helps organize the story, edit trip metadata, resolve review items,
  and prepare publication.
- `contributor`: adds photos, manages their own media, sees the shared story,
  and adds notes or comments.
- `viewer`: sees the private shared story but cannot upload or edit core story
  structure.
- `public viewer`: sees only published sanitized snapshots through share links.

The current backend already uses trip membership and roles. The important future
change is to make account-linked membership central to the product, including
non-owner trips in the user's library.

## Story Visibility Model

TripWeave should use separate visibility layers:

- Retained originals: raw uploads and raw metadata, private while available and never public.
- Member workspace: authenticated members can see authorized story context.
- Contributor-private media: contributors can restrict or withdraw their own
  media according to policy.
- Published snapshot: sanitized immutable version for public or unlisted sharing.

This keeps the product collaborative without treating every shared draft as
public.

## Publication Role

Publication should remain, but its meaning should be clearer:

- It is not the primary way group members experience a trip.
- It is a way to export or share a polished, sanitized snapshot outside the
  private member group.
- It should never expose originals, raw EXIF, raw locations, private media, or
  unapproved contributor content.
- Published links can be revoked without deleting the private story workspace.

In product language, "Publish" may eventually become "Share publicly" or
"Create public snapshot" to avoid implying that the story does not exist before
publication.

## Searchable Memory Archive

As stories accumulate, TripWeave should become searchable across a user's full
travel history.

Examples:

- "Korea trips"
- "Trips from 2015"
- "Trips with family"
- "Seoul"
- "Winter trips"
- "Stories where Mom uploaded photos"

The archive should support:

- Map-based browsing by country, region, city, or stop.
- Timeline browsing by year, season, month, or date range.
- Text search across titles, descriptions, notes, captions, places, and people.
- Filters by contributor, role, date, location, publication status, media count,
  and story state.

Each story should have enough indexed summary data to appear meaningfully in
search results:

- Date range.
- Representative image.
- Participants.
- Primary places.
- Map bounds or representative coordinates.
- Photo and note counts.
- Publication or sharing state.
- User's role in the story.

This turns TripWeave from a one-trip tool into a long-lived memory library.

## Suggested Future Features

Near-term product improvements:

- Show all account-linked trips in the logged-in user's home view, not only
  owner-created trips.
- Let contributors see an authenticated shared story view after joining.
- Make contributor workspace link to the member story view.

Collaborative story improvements:

- Notes on days, stops, moments, and photos.
- Comments or lightweight reactions for members.
- Contributor-visible activity such as new uploads and unresolved review items.
- Role-aware edit controls.
- Owner/editor review mode separate from member story mode.
- Member-visible captions and story text.

Library and search improvements:

- Story library with list, grid, map, and timeline views.
- Search by place, year, participant, and text.
- Story cards with representative photo, date range, places, contributors, and
  role badge.
- Map clusters for accumulated stories.
- Personal filters such as "owned by me", "shared with me", and "needs my
  photos".

Privacy and trust improvements:

- Clear visibility labels for private, trip-member-only, story-visible, and
  public.
- Contributor media withdrawal controls.
- Preview of what public publication will include.
- Clear distinction between private shared workspace and public snapshot.
- Account-linked audit trail for edits and notes.

## Implementation Implications

The current database model already has many useful foundations:

- `users`
- `trips`
- `trip_members`
- `trip_invitations`
- account sessions
- upload sessions and files
- media items and derivatives
- reconstruction tables
- review and edit operations
- story versions and share links

Important future backend work:

- Ensure `/trips` returns every active trip where `trip_members.user_id` matches
  the current user, regardless of role.
- Add tests proving non-owner account members see shared stories in their
  library.
- Add authorization tests for contributor and viewer story access.
- Add note/comment tables with Alembic migrations.
- Add story archive summary fields or a denormalized search index.
- Preserve provider-neutral storage contracts and avoid cloud provider terms in
  domain and application modules.

Important future frontend work:

- Rename the owner-centric home into a story library.
- Add role badges and shared-with-me affordances.
- Split owner/editor review tools from member story viewing.
- Polish invite acceptance for existing sessions, login, and account creation.
- Add map and timeline archive views for many stories.

## Product Summary

TripWeave should be understood as a private shared travel memory app first and a
public story publisher second.

The current MVP proves the local upload, processing, reconstruction, and
publication foundation. The next product evolution should make account-linked
membership, shared story viewing, collaborative notes, and searchable story
archives central to the experience. Families and friends should be able to
return years later, search for "Korea in 2015", open the shared story, see the
map and timeline, add context, and keep the memory alive together.
