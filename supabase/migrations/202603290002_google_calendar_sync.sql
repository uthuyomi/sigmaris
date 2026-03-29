alter table public.profiles
  add column if not exists google_calendar_sync_enabled boolean not null default false,
  add column if not exists google_calendar_sync_last_run_at timestamptz,
  add column if not exists google_calendar_sync_last_status text;

alter table public.events
  add column if not exists last_synced_at timestamptz,
  add column if not exists external_updated_at timestamptz;

create unique index if not exists idx_events_user_external_event_id
on public.events (user_id, external_event_id)
where external_event_id is not null;
