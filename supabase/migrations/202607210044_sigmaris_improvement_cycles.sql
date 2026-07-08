-- Phase C-full-2: SB-7 (improvement_cycle_gain) recording framework.
--
-- Phase D-H (the self-improvement system this table is meant to serve)
-- does not exist yet — nothing in this codebase writes to this table as
-- of this migration (see backend/app/services/improvement_cycle_store.py's
-- module docstring). This table exists so that, once Phase D's proposal
-- engine is built, it can start recording cycles immediately without a
-- schema migration blocking it.
--
-- Same service_role_only RLS pattern as sigmaris_eval_runs/
-- sigmaris_bench_runs/sigmaris_decision_log: meta/operational data about
-- Sigmaris's own self-improvement process, not user-owned content.
--
-- before_metrics/after_metrics/metric_gains are jsonb rather than fixed
-- columns per metric (unlike sigmaris_eval_runs' typed columns) because
-- the *set* of metrics available will grow over time (SB-5/SB-6 once their
-- target features exist — see docs/sigmaris/sigmaris_roadmap.md's SB-5/
-- SB-6 note) and a cycle may legitimately not have every metric available;
-- a jsonb snapshot avoids a schema migration every time the metric set
-- changes, at the cost of losing typed-column queryability (an acceptable
-- trade-off for a table nothing queries programmatically yet).

create table if not exists public.sigmaris_improvement_cycles (
  id                    uuid primary key default gen_random_uuid(),
  recorded_at           timestamptz not null default timezone('utc', now()),
  cycle_label           text not null,
  change_description    text not null,
  before_metrics        jsonb not null default '{}'::jsonb,
  after_metrics         jsonb not null default '{}'::jsonb,
  overall_gain_pct       float,
  metric_gains          jsonb not null default '[]'::jsonb,
  skipped_metrics       jsonb not null default '[]'::jsonb,
  notes                 text
);

create index if not exists idx_sigmaris_improvement_cycles_recorded_at
  on public.sigmaris_improvement_cycles (recorded_at desc);

alter table public.sigmaris_improvement_cycles enable row level security;

create policy "service_role_only" on public.sigmaris_improvement_cycles
  using (auth.role() = 'service_role');
