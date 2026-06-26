# 2026-05-18 travel reminder handoff

## Current goal

Make Sigmaris send smartphone travel reminder notifications for saved
Google Maps travel blocks without using Vercel Cron. The intended production
path is:

1. AI or UI creates a `travel_block` event.
2. `cron-job.org` calls `/api/cron/travel-reminders` every minute.
3. The Vercel API finds due travel blocks in Supabase.
4. The API sends Web Push to saved `push_subscriptions` when the travel block
   departure time has arrived.
5. The phone notification opens the saved Google Maps URL when tapped.

The app cannot open Google Maps automatically without a tap because mobile OSes
block arbitrary background app launches.

## Changes already pushed

- Vercel Cron was removed from both Vercel config files.
- `cron-job.org` is the external scheduler.
- The cron API still lives at `/api/cron/travel-reminders`.
- `CRON_SECRET` protects the cron API.
- `PRO_PLAN_OVERRIDE_EMAILS` lets selected login emails bypass Pro limits.
- The Pro override must be set on both:
  - Vercel frontend
  - Fly.io backend
- Backend AI prompts now know about Sigmaris' own travel reminder push
  notifications, separate from Google Calendar notifications.
- The cron endpoint now returns diagnostics:
  - `events`
  - `dueEvents`
  - `subscriptions`
  - `usersWithoutSubscriptions`
  - `sent`
  - `failedPushes`
  - `pushFailures`
  - `windowStart`
  - `windowEnd`

## Required production env

Vercel:

```text
CRON_SECRET=<same value used in cron-job.org Authorization header>
NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY=<VAPID public key>
WEB_PUSH_PRIVATE_KEY=<VAPID private key>
WEB_PUSH_SUBJECT=<mailto:... or URL>
SUPABASE_SERVICE_ROLE_KEY=<Supabase service role key>
PRO_PLAN_OVERRIDE_EMAILS=<comma-separated login emails, optional>
```

Fly.io backend:

```text
PRO_PLAN_OVERRIDE_EMAILS=<same comma-separated override emails if tool access should bypass Pro>
```

Also keep the existing Supabase, Google, OpenAI, and backend URL env values in
place.

## cron-job.org setup

- URL: `https://<vercel-production-domain>/api/cron/travel-reminders`
- Method: `POST`
- Schedule: every 1 minute
- Header key: `Authorization`
- Header value: `Bearer <CRON_SECRET>`
- Request body: empty

`Requires HTTP authentication` should remain off. That setting is Basic Auth,
not the bearer token used by this app.

## Debugging notification delivery

After deploying the latest frontend to Vercel, run the cron job manually and
inspect the JSON body.

If response is:

```json
{"events":0,"dueEvents":0,"sent":0}
```

There is no travel block whose departure/start time has just arrived inside the
cron lookup window. Create a travel block whose departure/start time is near the
current time, then check the cron response after that departure time passes.

If response is:

```json
{"events":1,"dueEvents":1,"subscriptions":0,"usersWithoutSubscriptions":1,"sent":0}
```

The travel block exists, but the phone has no saved Web Push subscription. On
the phone, log in, allow `Travel alerts`, and confirm a row appears in
`push_subscriptions`.

If response is:

```json
{"events":1,"dueEvents":1,"subscriptions":1,"sent":0,"failedPushes":1}
```

The phone subscription exists, but Web Push failed. Check `pushFailures`, VAPID
keys, browser notification permission, and stale subscriptions.

If response is:

```json
{"events":1,"dueEvents":1,"subscriptions":1,"sent":1}
```

The server sent the Push. Any remaining issue is likely phone/browser
notification settings, OS battery/background restrictions, or notification UI.

## Important date note

Old travel blocks are intentionally ignored. On 2026-05-18, a 2026-05-09 travel
block will never trigger. Test with a travel block whose departure time is about
to arrive, then wait for the next cron run.
