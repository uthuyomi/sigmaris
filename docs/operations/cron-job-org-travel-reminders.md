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
