# TripWeave User Introduction

TripWeave is an app that turns travel photos from multiple people into one shared trip story.

After a trip, each traveler can upload the photos scattered across their phones and cameras. TripWeave uses time and location clues from those photos to organize the trip into days, places, routes, and memorable moments. Instead of reviewing every photo one by one, users focus on the parts that need human judgment, then share the finished story as an interactive map and timeline.

## Who Is It For?

TripWeave is useful when you want to:

- Collect photos from family, friends, or coworkers after a shared trip.
- Rebuild the real sequence of a trip from many camera rolls.
- See where the group went on a map.
- Create something richer than a plain photo album.
- Share a travel story without exposing original files or sensitive location metadata.

## What TripWeave Does

TripWeave's core job is to weave scattered media into one shared travel record.

1. Create a trip

   A trip owner creates a new trip and sets basic details such as title, dates, and timezone.

2. Invite contributors

   The owner invites fellow travelers so they can add their own photos. Contributors keep ownership and deletion control over the media they upload.

3. Upload photos

   Contributors upload JPEG or HEIC photos. Original files are treated as private processing inputs, not public story content.

4. Organize automatically

   TripWeave extracts capture time, location, and file details, then groups the trip into days, travel segments, visited places, and smaller moments.

5. Review only exceptions

   Users do not need to inspect every asset manually. TripWeave highlights items that may need attention, such as missing timestamps, uncertain locations, possible wrong-day assignments, or grouping issues.

6. Correct and confirm

   Users can fix timestamps, locations, groupings, visibility, and related story details. Human corrections take priority over automated guesses.

7. Share the trip story

   The organized trip can be explored as a map-and-timeline story. Public stories use sanitized derivatives and story data instead of original private files.

## Key Features

### Shared Photo Collection

Each trip can include multiple contributors. TripWeave records who uploaded each media item and respects contributor ownership.

### Time And Location Based Organization

TripWeave uses capture timestamps and GPS data to reconstruct the flow of a trip. It groups photos from the same day, the same place, and the same narrative moment.

### Map And Timeline

The final experience is not just a photo list. Users can explore the trip through a synchronized map and timeline, moving between days, stops, routes, and moments.

### Review By Exception

Automated reconstruction is helpful, but it is not always perfect. TripWeave surfaces low-confidence results, missing data, possible clock issues, and questionable groupings so users can focus on the parts that matter.

### Human Corrections Take Priority

When a user corrects a time, location, grouping, or visibility decision, that correction wins over automated output. The system is designed to preserve human decisions across future reconstruction runs.

### Safer Public Stories

Published stories do not expose original photos. They use generated derivatives with sensitive metadata removed, plus story data that is appropriate for sharing.

### Local-First Design

TripWeave is designed to prove its full MVP locally first. Its default foundation uses local storage, a local database, and local processing jobs while avoiding dependence on any single cloud provider.

## Basic User Flow

1. Create an account and sign in.
2. Create a new trip.
3. Invite the people who traveled with you.
4. Each contributor uploads photos.
5. TripWeave processes the photos and reconstructs the trip structure.
6. The owner or editors review exceptions and make corrections.
7. The group explores the organized trip through a map and timeline.
8. When ready, the owner creates a public story snapshot to share.

## Privacy And Ownership

TripWeave assumes travel photos, locations, timestamps, and contributor identities are sensitive personal data.

- Original files are not used in public stories.
- Original metadata is treated as private information.
- Contributors keep ownership and deletion control over their media.
- Published stories contain sanitized derivatives and curated story data.
- Public links do not expose original storage locations or permanent storage URLs.

## What TripWeave Is Not

TripWeave is not just a photo storage service or a cloud backup tool. Its main purpose is not to keep every original file forever.

TripWeave is about understanding the shape of a shared trip, correcting it where needed, and turning it into a story people can revisit or share safely. The focus is the travel narrative, collaborative memory, and privacy-aware sharing experience.

## In One Sentence

TripWeave turns travel photos from multiple people into a safe shared trip story organized by days, places, moments, map, and timeline.
