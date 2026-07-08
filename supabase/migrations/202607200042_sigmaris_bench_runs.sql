-- Phase C-full-1: public-benchmark (LongMemEval / LoCoMo) score records.
--
-- sigmaris_bench_runs is deliberately a *separate* table from
-- sigmaris_eval_runs (Phase C-mini's internal, self-generated-testset
-- metrics — see docs/sigmaris/phase_c_mini_report.md section 1 for why that
-- distinction matters). This table holds results from running Sigmaris's
-- real memory pipeline against LongMemEval/LoCoMo's public, third-party
-- question sets, graded via LLM-as-a-Judge — the "objective, externally
-- comparable" number, as opposed to C-mini's "fast internal PDCA signal".
-- Keeping them in separate tables (rather than adding columns to
-- sigmaris_eval_runs) makes that distinction structurally unmissable
-- whenever either table is queried, not just documented in a comment.
--
-- Same service_role_only RLS pattern as sigmaris_eval_runs/
-- sigmaris_decision_log/sigmaris_internal_state: meta/operational data
-- about Sigmaris itself, not user-owned content.

create table if not exists public.sigmaris_bench_runs (
  id                    uuid primary key default gen_random_uuid(),
  run_at                timestamptz not null default timezone('utc', now()),
  dataset               text not null check (dataset in ('longmemeval', 'locomo')),
  dataset_version       text,
  instance_count        integer not null default 0,
  total_questions       integer not null default 0,
  correct_count         integer not null default 0,
  overall_accuracy      float,
  category_counts       jsonb not null default '{}'::jsonb,
  category_accuracy     jsonb not null default '{}'::jsonb,
  adversarial_accuracy  float,
  notes                 text,
  details               jsonb not null default '{}'::jsonb
);

create index if not exists idx_sigmaris_bench_runs_dataset_run_at
  on public.sigmaris_bench_runs (dataset, run_at desc);

alter table public.sigmaris_bench_runs enable row level security;

create policy "service_role_only" on public.sigmaris_bench_runs
  using (auth.role() = 'service_role');
