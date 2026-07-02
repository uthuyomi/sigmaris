# Sigmaris Wear OS

Wear OS client for talking to Sigmaris by voice or text.

## What it does

- Logs in to Supabase with email/password and stores only the refresh token
  (the app silently re-derives a fresh access token on each launch and on
  401s — no JWT ever needs to be typed by hand).
- Starts Wear OS voice recognition from the watch, or accepts typed input.
- Sends messages to the existing backend `POST /api/orchestrator/chat`.
- A `/status` quick-action chip asks Sigmaris to summarize its current
  cognitive state.
- Shows Sigmaris' reply on the watch and reads it aloud with TextToSpeech.
- Tapping a Sigmaris Pushover notification (which includes a `sigmaris://chat`
  deep link) opens the app directly, when the notification bridges to the watch.

## Setup

1. Copy `local.properties.example` to `local.properties` (already gitignored)
   and fill in:
   - `sdk.dir`: your Android SDK path.
   - `SUPABASE_URL` / `SUPABASE_KEY`: from the Supabase project dashboard
     (Project Settings > API) — same values as `frontend/.env.local`'s
     `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
   - `BACKEND_URL`: the Sigmaris backend's LAN address, e.g.
     `http://192.168.179.11:8000`.
2. Open `wearos` in Android Studio and sync Gradle.
3. Run the `app` module on a Wear OS emulator or watch.

These values are compiled into `BuildConfig` at build time — nothing is
hardcoded in source, and `local.properties` is never committed.

## Run

1. On first launch, enter your Supabase account email/password on the login
   screen. The password itself is never stored — only the resulting
   Supabase refresh token is kept in local app storage.
2. Tap `接続確認` to verify the watch can reach the backend.
3. Tap `話す`, speak, and wait for Sigmaris' response — the app sends the
   recognized speech automatically when voice input finishes. You can also
   tap `/status 認知状態確認` for a quick cognitive-state check.
4. Use `ログアウト` to clear the stored session (e.g. to switch accounts).

## Backend server

Start FastAPI on the Ubuntu server so other devices on the Wi-Fi can reach it:

```bash
cd /path/to/shift-pilot-ai/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server firewall must allow inbound traffic to port `8000`.

## Notes

This first version talks directly to the backend. For a production watch app,
move authentication into a phone companion app and pass short-lived requests
through the Wear OS Data Layer.
