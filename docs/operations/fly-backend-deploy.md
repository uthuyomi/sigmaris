# Fly.io Backend Deploy

Deploy the ShiftPilotAI FastAPI backend from `backend/` as a Fly.io app.

## First Setup

```powershell
cd backend
fly launch --no-deploy
```

If the `app` name in `fly.toml` is already taken, change it to a unique Fly.io app name.

## Secrets

```powershell
fly secrets set `
  FRONTEND_ORIGIN="https://your-frontend.vercel.app" `
  NEXT_PUBLIC_SUPABASE_URL="..." `
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="..." `
  OPENAI_API_KEY="..." `
  OPENAI_MODEL="gpt-5-nano" `
  GOOGLE_CLIENT_ID="..." `
  GOOGLE_CLIENT_SECRET="..." `
  GOOGLE_REDIRECT_URI="https://your-frontend.vercel.app/auth/callback" `
  GOOGLE_CALENDAR_ID="primary" `
  GOOGLE_MAPS_API_KEY="..."
```

Set `OPENAI_IMPORT_MODEL` only if import extraction should use a separate model.

## Deploy

```powershell
fly deploy
fly status
fly checks list
```

## Frontend Env

Set this in the Vercel frontend project and redeploy the frontend:

```text
BACKEND_API_BASE_URL=https://<fly-app-name>.fly.dev
```

## Health Check

```powershell
curl https://<fly-app-name>.fly.dev/health
curl https://<fly-app-name>.fly.dev/api/health
```
