-- Phase BA3: Memory Snapshot.
--
-- Cold-path aggregate of the existing B6/B9/B14/B16 outputs. This table
-- intentionally does not replace the source tables or extraction logic:
-- weekly jobs still write sigmaris_topic_log, sigmaris_entities,
-- sigmaris_entity_relations, sigmaris_user_preference_patterns, and
-- sigmaris_goal_alignment_flags. The snapshot only stores the bounded
-- response-time view the orchestrator used to fetch from those tables one
-- by one.

create table if not exists public.sigmaris_user_snapshot (
  user_id                 uuid primary key,
  preference_patterns    jsonb not null default '[]'::jsonb,
  topic_state            jsonb not null default '{"current": null, "previous": null}'::jsonb,
  goal_alignment_flags   jsonb not null default '[]'::jsonb,
  entities               jsonb not null default '[]'::jsonb,
  relations              jsonb not null default '[]'::jsonb,
  generated_at           timestamptz not null default timezone('utc', now()),
  created_at             timestamptz not null default timezone('utc', now()),
  updated_at             timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_user_snapshot_generated_at
  on public.sigmaris_user_snapshot (generated_at desc);

alter table public.sigmaris_user_snapshot enable row level security;

create policy "service_role_only" on public.sigmaris_user_snapshot
  using (auth.role() = 'service_role');

-- Reuses the shared trigger function from 202606240016_fact_memory.sql.
create trigger trg_sigmaris_user_snapshot_updated_at
  before update on public.sigmaris_user_snapshot
  for each row execute function public.set_updated_at();
