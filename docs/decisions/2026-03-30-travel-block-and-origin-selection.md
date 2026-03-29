# 2026-03-30 Travel Block And Origin Selection

## Decision
- Add a travel-block confirmation flow instead of keeping route planning read-only.
- Let the user choose the origin from home, current location, saved places, or custom input.
- Save travel blocks to the app database first, then mirror to Google Calendar when sync is enabled.

## Reason
- Route advice alone is not enough for schedule integrity. The travel time must become part of the schedule.
- Departure origin changes the route materially, so it needs to be a first-class input.
- Saving to the app database keeps conflict checks and future timeline features under app control.

## Result
- Travel planning now supports preview, warning, confirmation, and insertion.
- Settings now include a place-management panel for home address and saved departure points.
