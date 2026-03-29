-- ShiftPilotAI initial application schema
-- Apply with Supabase SQL Editor or supabase db push

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_url text,
  timezone text not null default 'Asia/Tokyo',
  home_address text,
  default_grain_minutes integer not null default 10 check (default_grain_minutes in (5, 10, 15, 30, 60)),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.saved_locations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  label text not null,
  address text not null,
  latitude double precision,
  longitude double precision,
  location_type text not null default 'custom' check (location_type in ('home', 'work', 'custom')),
  is_default_departure boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.calendar_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  provider text not null check (provider in ('google', 'app')),
  provider_account_email text,
  provider_calendar_id text not null,
  display_name text,
  color text,
  is_primary boolean not null default false,
  access_role text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (provider, provider_calendar_id, user_id)
);

create table if not exists public.import_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  source_type text not null check (source_type in ('sheet', 'image', 'chat', 'manual')),
  source_label text,
  source_url text,
  status text not null default 'previewed' check (status in ('previewed', 'confirmed', 'committed', 'failed')),
  raw_payload jsonb not null default '{}'::jsonb,
  extracted_payload jsonb not null default '[]'::jsonb,
  committed_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  calendar_connection_id uuid references public.calendar_connections(id) on delete set null,
  import_job_id uuid references public.import_jobs(id) on delete set null,
  title text not null,
  description text,
  location_text text,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  status text not null default 'confirmed' check (status in ('draft', 'confirmed', 'cancelled')),
  source_type text not null default 'manual' check (source_type in ('manual', 'chat', 'sheet', 'image', 'calendar_sync')),
  external_event_id text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  check (ends_at > starts_at)
);

create table if not exists public.event_travel_plans (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events(id) on delete cascade,
  origin_label text,
  origin_address text,
  destination_label text,
  destination_address text,
  travel_mode text not null check (travel_mode in ('transit', 'driving', 'walking')),
  recommended_departure_at timestamptz,
  estimated_arrival_at timestamptz,
  duration_minutes integer,
  route_summary text,
  route_steps jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists idx_saved_locations_default_departure
on public.saved_locations (user_id)
where is_default_departure = true;

create unique index if not exists idx_calendar_connections_primary
on public.calendar_connections (user_id)
where is_primary = true;

create index if not exists idx_events_user_starts_at
on public.events (user_id, starts_at);

create index if not exists idx_import_jobs_user_created_at
on public.import_jobs (user_id, created_at desc);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
    new.raw_user_meta_data ->> 'avatar_url'
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_saved_locations_updated_at on public.saved_locations;
create trigger set_saved_locations_updated_at
  before update on public.saved_locations
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_calendar_connections_updated_at on public.calendar_connections;
create trigger set_calendar_connections_updated_at
  before update on public.calendar_connections
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_import_jobs_updated_at on public.import_jobs;
create trigger set_import_jobs_updated_at
  before update on public.import_jobs
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_events_updated_at on public.events;
create trigger set_events_updated_at
  before update on public.events
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_event_travel_plans_updated_at on public.event_travel_plans;
create trigger set_event_travel_plans_updated_at
  before update on public.event_travel_plans
  for each row execute procedure public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.saved_locations enable row level security;
alter table public.calendar_connections enable row level security;
alter table public.import_jobs enable row level security;
alter table public.events enable row level security;
alter table public.event_travel_plans enable row level security;

create policy "profiles_select_own"
on public.profiles
for select
using (auth.uid() = id);

create policy "profiles_update_own"
on public.profiles
for update
using (auth.uid() = id)
with check (auth.uid() = id);

create policy "saved_locations_all_own"
on public.saved_locations
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "calendar_connections_all_own"
on public.calendar_connections
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "import_jobs_all_own"
on public.import_jobs
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "events_all_own"
on public.events
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "event_travel_plans_all_own"
on public.event_travel_plans
for all
using (
  exists (
    select 1
    from public.events
    where public.events.id = public.event_travel_plans.event_id
      and public.events.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from public.events
    where public.events.id = public.event_travel_plans.event_id
      and public.events.user_id = auth.uid()
  )
);
