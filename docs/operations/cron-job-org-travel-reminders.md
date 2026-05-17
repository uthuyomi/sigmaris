# cron-job.org travel reminders

Use cron-job.org as the external scheduler for travel reminder push notifications.

## Target

- URL: `https://<production-domain>/api/cron/travel-reminders`
- Method: `POST`
- Schedule: every minute (`* * * * *`)
- Header:
  - Name: `Authorization`
  - Value: `Bearer <CRON_SECRET>`

## Required environment variables

Set the same `CRON_SECRET` value in the production hosting environment and in
cron-job.org.

The app endpoint rejects requests in production unless this header exactly
matches:

```text
Authorization: Bearer <CRON_SECRET>
```

## Notes

- Vercel Cron is intentionally not configured in `vercel.json`.
- The cron endpoint still lives at `/api/cron/travel-reminders`.
- `GET` also works because the route aliases `GET` to `POST`, but `POST` is the
  preferred method for the external scheduler.
- Running every minute matches the current reminder lookup window.

## Pro plan override

For internal operators or testers, set this production environment variable to
treat specific login emails as Pro users without a Stripe subscription.
Set it in both the Vercel frontend and the Fly.io backend when backend chat
tools are enabled:

```text
PRO_PLAN_OVERRIDE_EMAILS=first@example.com,second@example.com
```

Email matching is case-insensitive. Do not expose this as a `NEXT_PUBLIC_`
variable.
