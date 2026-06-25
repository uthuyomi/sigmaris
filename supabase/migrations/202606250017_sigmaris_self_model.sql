-- Sigmaris self-model: identity, goals, observed patterns, and belief updates.
-- Single-row table managed exclusively by the backend service role.

create table if not exists public.sigmaris_self_model (
  id             uuid        primary key default gen_random_uuid(),
  version        integer     not null default 1 check (version > 0),
  identity_statement text    not null default '',
  current_goals  jsonb       not null default '[]'::jsonb,
  observed_patterns jsonb    not null default '[]'::jsonb,
  belief_updates jsonb       not null default '[]'::jsonb,
  last_reflected_at timestamptz,
  created_at     timestamptz not null default timezone('utc', now()),
  updated_at     timestamptz not null default timezone('utc', now())
);

-- Prevent accidental multi-row inserts: at most one row is allowed.
create unique index if not exists sigmaris_self_model_singleton
  on public.sigmaris_self_model ((true));

-- Discrepancy log: expected vs actual behavior observations.
create table if not exists public.sigmaris_self_discrepancies (
  id                  uuid        primary key default gen_random_uuid(),
  expected_behavior   text        not null,
  actual_behavior     text        not null,
  discrepancy_note    text        not null default '',
  resolved            boolean     not null default false,
  created_at          timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_self_discrepancies_resolved
  on public.sigmaris_self_discrepancies (resolved, created_at desc);

-- Auto-update updated_at on sigmaris_self_model.
-- Reuse the set_updated_at() function created in migration 202606240016.
create trigger trg_sigmaris_self_model_updated_at
  before update on public.sigmaris_self_model
  for each row execute function public.set_updated_at();

-- RLS: enable with no user policies → only service_role (bypasses RLS) can access.
alter table public.sigmaris_self_model       enable row level security;
alter table public.sigmaris_self_discrepancies enable row level security;
