-- Phase R-3 (docs/sigmaris/phase_r_report.md): persistence for RC-1..RC-5
-- (循環健全性指標 / Reflexive Cycle metrics).
--
-- Deliberately a separate table from sigmaris_eval_runs (Phase C-mini/
-- C-full's memory_precision/response_error_rate/etc.) and sigmaris_
-- improvement_cycles (SB-7) — RC indicators measure whether the
-- Experience->Memory->Temporal Evaluation->Belief->Policy->Action loop
-- itself is functioning, not memory retrieval accuracy or self-improvement
-- proposals. Mixing the two into one table would make "which metric
-- family does this row belong to" ambiguous at read time.
--
-- Same service_role_only, single-tenant pattern as sigmaris_eval_runs/
-- sigmaris_decision_log/sigmaris_experience: this is Sigmaris's own
-- derived measurement data, not user-owned content.
--
-- Headline scores for each RC indicator get their own float column (so
-- "how has rc2_score trended over the last 10 runs" is a plain SQL query,
-- matching sigmaris_eval_runs' precedent of promoting memory_precision
-- etc. to real columns rather than burying everything in jsonb). Anything
-- more detailed (per-pattern belief-flip list, per-flag alignment ratios,
-- the belief_snapshot RC-3 needs to diff against on the *next* run, chat
-- order violation samples, etc.) goes in `details` jsonb, mirroring
-- sigmaris_eval_runs.details.

create table if not exists public.sigmaris_cycle_health_runs (
  id                     uuid primary key default gen_random_uuid(),
  run_at                 timestamptz not null default timezone('utc', now()),
  window_days            integer not null,
  period_from            timestamptz,
  period_to              timestamptz,

  -- RC-1: Cycle Completion Rate
  rc1_total_experiences        integer,
  rc1_reached_count             integer,
  rc1_raw_completion_rate       float,
  rc1_eligible_count            integer,
  rc1_eligible_completion_rate  float,

  -- RC-2: Temporal Consistency Score
  rc2_score                             float,
  rc2_chat_pairs_checked                integer,
  rc2_chat_order_violation_count        integer,
  rc2_event_experience_checked          integer,
  rc2_event_experience_violation_count  integer,

  -- RC-3: Belief Stability Index
  rc3_score                     float,
  rc3_comparable_pattern_count  integer,
  rc3_flip_count                 integer,
  rc3_unsupported_flip_count     integer,

  -- RC-4: Policy-Belief Alignment
  rc4_score            float,
  rc4_flags_evaluated   integer,

  -- RC-5: Cycle Break Detection
  rc5_status          text check (rc5_status in ('insufficient_history', 'healthy', 'break_detected')),
  rc5_broke_metrics    jsonb not null default '[]'::jsonb,

  notes    text,
  details  jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_cycle_health_runs_run_at
  on public.sigmaris_cycle_health_runs (run_at desc);

alter table public.sigmaris_cycle_health_runs enable row level security;

create policy "service_role_only" on public.sigmaris_cycle_health_runs
  using (auth.role() = 'service_role');
