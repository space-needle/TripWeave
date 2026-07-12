# ADR 0005: Versioned Story Publication

## Status

Accepted

## Context

TripWeave publishes shared trip stories from private source media. Original files and original metadata may include sensitive information and must not be exposed as public artifacts.

Contributors retain ownership and deletion control, so publication needs an auditable version model rather than an uncontrolled live view of private data.

## Decision

Publication creates versioned story snapshots containing sanitized derivatives and sanitized story data.

Published stories never serve originals. Corrections, attribution, visibility choices, and map geometry included in a publication version are captured as part of that version.

## Consequences

Publication can be reviewed, tested, and rolled forward as explicit versions.

Contributor deletion or withdrawal requires a clear policy for future and existing publication versions.

The system must regenerate or invalidate derivatives and publication versions when privacy or ownership rules require it.
