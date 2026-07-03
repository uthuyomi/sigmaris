-- Phase C-mini: minimal evaluation baseline for Phase B's per-feature PDCA loop.
--
-- sigmaris_eval_runs is an append-only, timestamped record of the 3 internal
-- metrics (memory_f1_score, rag_ndcg_score, response_error_rate) computed by
-- backend/scripts/run_eval.py. It is meta/operational data about Sigmaris
-- itself, not user-owned content, so it follows the same
-- service_role_only RLS pattern as sigmaris_decision_log and
-- sigmaris_internal_state rather than per-user RLS.
--
-- These are internal, testset-derived indicators — not scores on an
-- external, objective benchmark (LongMemEval/LoCoMo). See
-- docs/sigmaris/phase_c_mini_report.md section 1 for why that distinction
-- matters.

create table if not exists public.sigmaris_eval_runs (
  id                    uuid primary key default gen_random_uuid(),
  run_at                timestamptz not null default timezone('utc', now()),
  testset_version       text,
  testset_size          integer not null default 0,
  memory_precision      float,
  memory_recall         float,
  memory_f1_score       float,
  rag_ndcg_score        float,
  response_error_rate   float,
  response_sample_size  integer,
  notes                 text,
  details               jsonb not null default '{}'::jsonb
);

create index if not exists idx_sigmaris_eval_runs_run_at
  on public.sigmaris_eval_runs (run_at desc);

alter table public.sigmaris_eval_runs enable row level security;

create policy "service_role_only" on public.sigmaris_eval_runs
  using (auth.role() = 'service_role');
