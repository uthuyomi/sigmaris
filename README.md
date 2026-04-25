# ShiftPilotAI

ShiftPilotAI is an AI-assisted scheduling app that turns shift table screenshots, Google Sheets, and chat instructions into reviewable calendar events. It can also calculate travel time for events with locations and create travel blocks before the event starts.

The project is built as a full-stack application with a Next.js frontend, a FastAPI backend, Supabase Auth/database, OpenAI-powered extraction and chat, and Google Calendar / Sheets / Maps integrations.

> Status: active prototype. The core workflow is implemented, but this is not a polished hosted product yet.

[日本語版はこちら](./README_ja.md)

---

## Why This Exists

Manually copying a shift table into a calendar is tedious. It gets even worse when every event also needs a location, a departure time, and travel planning.

ShiftPilotAI focuses on a practical workflow:

1. Send a shift table image, a Google Sheets URL, or a schedule note.
2. Extract event candidates with AI.
3. Review the detected title, date, start time, and end time.
4. Save reviewed events to Google Calendar.
5. Calculate travel time and departure time for events with locations.
6. Review everything in a month calendar or day timeline.

The goal is not to be another generic calendar UI. The goal is to remove the repetitive schedule cleanup work around shifts, appointments, and location-based plans.

---

## Core Features

### AI Schedule Import

- Extract schedule candidates from shift table screenshots or photos.
- Read schedule rows from Google Sheets URLs.
- Return structured event candidates with title, date, start time, end time, description, and confidence.
- Keep a review step before events are saved.

### Chat-First Scheduling

- Chat with the assistant about schedules, existing events, and travel planning.
- Store chat conversations by thread.
- Rename and delete chat threads.
- Route chat requests to specialized backend tools.
- Use app data and Google data as context for more practical answers.

### Google Calendar Integration

- Sign in with Google through Supabase Auth.
- Read Google Calendar events.
- Create reviewed events in Google Calendar.
- Sync Google Calendar events into the app database.
- Create travel blocks and optionally sync them to Google Calendar.

### Google Sheets Integration

- Read the first sheet from a Google Sheets URL.
- Preview rows before passing them into the extraction pipeline.
- Use the extracted rows to create event candidates.

### Travel Planning

- Calculate routes with Google Maps.
- Supported modes: car, bicycle, walking.
- Use saved home address, saved locations, or custom origins.
- Calculate a recommended departure time based on the event start time and arrival lead setting.
- Save travel plans as app events linked to the destination event.

Current limitation: public transit route search is intentionally unavailable in the current implementation.

### Calendar And Timeline Views

- Month calendar view for schedule overview.
- Day timeline view for event flow and travel blocks.
- Event source labels for app-created and synced events.
- Responsive app shell with chat, calendar, timeline, and settings areas.

### User Preferences

- Display language selection.
- AI response tone selection.
- Preferred travel mode.
- Arrival lead minutes.
- Saved locations and home address.
- Google Calendar sync on/off.

Supported display locales include Japanese, English, Korean, Simplified Chinese, Traditional Chinese, Spanish, French, German, Brazilian Portuguese, Italian, Indonesian, Thai, and Vietnamese.

---

## Tech Stack

### Frontend

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS
- assistant-ui
- Supabase SSR client
- Google APIs Node client
- Zod

### Backend

- FastAPI
- Python 3.12+
- OpenAI Responses API
- Google API Python client
- Supabase REST access through user JWT
- Pydantic validation

### Data And Auth

- Supabase Auth
- Supabase Postgres
- Row Level Security policies
- Google OAuth through Supabase

### External Integrations

- OpenAI
- Google Calendar
- Google Sheets
- Google Maps

---

## Architecture

```text
ShiftPilotAI/
├─ frontend/     Next.js app, UI, API route proxy, Supabase session handling
├─ backend/      FastAPI service, OpenAI orchestration, Google/app tools
├─ supabase/     Database migrations and RLS policies
└─ docs/         Design notes, decisions, requirements, operation logs
```

### Request Flow

```text
Browser
  ↓
Next.js frontend
  ↓
Next.js API routes
  ↓
FastAPI backend
  ↓
OpenAI / Google APIs / Supabase REST
```

The frontend owns the user-facing UI and session handling. The backend owns AI orchestration, intent routing, tool execution, import extraction, and Google Maps route planning.

Supabase RLS keeps app data scoped to the authenticated user. Backend Supabase access uses the user's JWT instead of a service role key.

---

## Security Notes

The project includes several security-oriented guardrails:

- High-cost import and route-planning APIs require authentication.
- Backend Google, import, mobility, and app-data routes require Bearer auth.
- Google provider tokens are stored in HTTP-only cookies.
- Shared `GOOGLE_REFRESH_TOKEN` fallback is intentionally not used.
- Request payload sizes are capped for image import, chat messages, Google operations, and extracted candidates.
- Production FastAPI docs/redoc are disabled when `APP_ENV=production`.
- Supabase RLS policies restrict profile, event, location, calendar connection, import job, chat thread, and chat message access to the owning user.
- `npm audit --omit=dev` currently reports zero vulnerabilities.

Recommended production additions:

- Add rate limiting at the edge or API gateway.
- Keep the FastAPI backend private if possible and only expose it through the frontend/server network.
- Add structured audit logs for Google write/delete operations.
- Run Python dependency auditing in CI with `pip-audit`.
- Restrict Google OAuth redirect URIs to exact production and local development URLs.

---

## Local Development

### Prerequisites

- Node.js compatible with Next.js 16
- Python 3.12+
- A Supabase project
- Google Cloud OAuth client
- Google Calendar API enabled
- Google Sheets API enabled
- Google Maps APIs enabled
- OpenAI API key

### 1. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 2. Install Backend Dependencies

```bash
cd backend
python -m pip install -e .
```

### 3. Configure Environment Variables

Create `frontend/.env.local` for the frontend and backend-shared values used during local development.

```bash
# Frontend / Supabase
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=

# Backend URL used by Next.js API routes
BACKEND_API_BASE_URL=http://127.0.0.1:8000

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_IMPORT_MODEL=gpt-5-nano

# Google OAuth / APIs
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_CALENDAR_ID=primary
GOOGLE_MAPS_API_KEY=
```

For backend-only deployment, use `backend/.env` with the same backend-relevant variables:

```bash
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:3000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_IMPORT_MODEL=gpt-5-nano
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_CALENDAR_ID=primary
GOOGLE_MAPS_API_KEY=
```

Do not configure a shared `GOOGLE_REFRESH_TOKEN`. Google operations should use the logged-in user's provider token.

### 4. Apply Supabase Migrations

The schema and RLS policies live in `supabase/migrations/`.

Apply them with your Supabase workflow, for example through the Supabase CLI:

```bash
supabase db push
```

The migrations define tables for profiles, saved locations, calendar connections, import jobs, events, event travel plans, chat threads, and chat messages.

### 5. Start The Backend

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Health checks:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/api/health
```

### 6. Start The Frontend

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:3000
```

---

## Useful Commands

### Frontend

```bash
cd frontend
npm run dev
npm run lint
npm run build
npm audit --omit=dev
```

### Backend

```bash
cd backend
python -m compileall app
python -m uvicorn app.main:app --reload --port 8000
```

---

## Main Routes

### Frontend Pages

- `/` - public landing page
- `/login` - Google login entry
- `/calendar` - month calendar
- `/timeline` - day timeline
- `/chat` - AI scheduling chat
- `/settings` - language, sync, travel, and integration settings

### Next.js API Routes

- `/api/chat`
- `/api/chat/threads`
- `/api/import/preview`
- `/api/import/commit`
- `/api/mobility/plan`
- `/api/mobility/schedule`
- `/api/sync/google-calendar`
- `/api/settings/*`

### FastAPI Routes

- `/health`
- `/api/health`
- `/api/chat/stream`
- `/api/import/preview`
- `/api/mobility/plan`
- `/api/google/calendar/list`
- `/api/google/calendar/create`
- `/api/google/calendar/delete`
- `/api/google/calendar/delete-range`
- `/api/google/sheets/preview`
- `/api/app/events/search`
- `/api/app/home-context`
- `/api/app/chat/threads/{thread_id}`
- `/api/app/chat/messages/replace`

Most backend API routes require a user Bearer token.

---

## Current Limitations

- Public transit route planning is not implemented.
- The app currently focuses on single-user authenticated workflows, not team scheduling.
- The import pipeline still depends on LLM extraction quality and requires user review.
- Production deployments should add rate limiting and operational monitoring.
- Some app-calendar-only import behavior is staged; Google Calendar integration is the primary save path.

---

## Roadmap Ideas

- Public transit support.
- Better import review UI with batch edit.
- More robust recurring shift handling.
- Mobile-first capture flow for shift table photos.
- Calendar conflict resolution assistant.
- Per-user Google token storage strategy beyond cookies.
- Deployment guide with Vercel, Fly.io, Render, or similar platforms.
- Test suite for API route security and import validation.

---

## Repository Topics

Suggested GitHub topics:

```text
ai
scheduler
google-calendar
google-sheets
google-maps
shift-scheduling
travel-planning
nextjs
fastapi
supabase
openai
typescript
python
```

---

## License

No license has been selected yet. Add a license before distributing or accepting external contributions.

---

## Author

Kaisei Yasuzaki

