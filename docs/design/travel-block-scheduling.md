# Travel Block Scheduling

## Goal
- Pick a departure origin from home, current location, saved places, or custom input.
- Calculate the latest departure that still reaches the event on time.
- Preview a travel block before inserting it.
- Warn when the travel block overlaps with existing events.
- Save the travel block to the app database and optionally to Google Calendar when sync is enabled.

## Implemented Flow
1. The selected event provides destination and target start time.
2. The user picks `home`, `current`, `saved`, or `custom` origin.
3. Transit uses Google Maps with `arrival_time`.
4. Driving and walking use Google Maps route duration and reverse-calculate the departure time from the event start.
5. The API builds a travel block from `recommendedDepartureIso` to the event start.
6. Existing events in the same window are checked for overlap.
7. The UI previews route details and conflict warnings.
8. After confirmation, a travel block event is inserted into `events`.
9. A matching `event_travel_plans` record is written for the target event.
10. If Google Calendar sync is enabled, the travel block is also inserted into Google Calendar.

## Key Files
- `src/app/api/mobility/schedule/route.ts`
- `src/lib/google/maps.ts`
- `src/lib/events.ts`
- `src/lib/locations.ts`
- `src/components/mobility-panel.tsx`
- `src/components/saved-locations-panel.tsx`

## Limits
- Saved locations can be created and deleted in settings, but they do not yet support edit mode.
- Driving and walking reverse-calculation is based on the route duration returned for the target arrival window, not a multi-pass traffic simulation.
- Conflict handling warns and supports force-save, but does not yet auto-shift neighboring events.
