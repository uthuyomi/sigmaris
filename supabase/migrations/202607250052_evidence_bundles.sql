-- Phase D-1 (docs/sigmaris/phase_d_report.md): persistence for periodic
-- evidence-aggregation runs (the material-gathering layer feeding Phase D-2's
-- future hypothesis generation). Computed by scripts/run_evidence_aggregation.py
-- from three EXISTING sources -- sigmaris_cycle_health_runs (Phase R),
-- sigmaris_grounding_health_runs (Phase G), sigmaris_experience with
-- category='proposal' (Phase S-2 Mastery Drive) -- plus a text-parsed read
-- of docs/sigmaris/bug_inventory.md. No new telemetry/data collection was
-- added anywhere upstream; this table only records the result of each
-- aggregation run itself.
--
-- Mirrors sigmaris_grounding_health_runs' / sigmaris_cycle_health_runs' shape
-- deliberately: one row per CLI invocation, headline counts promoted to real
-- integer columns, the full itemized/prioritized evidence list in `items`
-- jsonb. Kept as a SEPARATE table from those two and from sigmaris_eval_runs
-- (C-mini/C-full) -- same reasoning as their own migration comments: this
-- table measures "what evidence was gathered for self-improvement", a
-- different concern from cycle health, grounding quality, or memory-retrieval
-- accuracy. Mixing metric/evidence families into one table makes "which
-- family does this row belong to" ambiguous at read time.
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_evidence_bundles (
  id                            uuid primary key default gen_random_uuid(),
  run_at                        timestamptz not null default timezone('utc', now()),
  item_limit                    integer not null,

  -- How many rows/records were actually read from each of the three DB
  -- sources (bug_inventory.md's row count is separate, it's a file not a
  -- DB source). Zero is a legitimate value (e.g. no RC runs recorded yet
  -- because the Phase R migration hasn't been applied) -- distinct from
  -- "this source failed to read", which is not represented in this table
  -- (fail-open reads simply return an empty list, same as every other
  -- Sigmaris measurement store).
  phase_r_runs_checked          integer,
  phase_g_runs_checked          integer,
  mastery_proposals_checked     integer,
  bug_inventory_rows_checked    integer,

  -- Headline counts per evidence category (see evidence_aggregation.py).
  metric_degradation_count      integer not null default 0,
  recurring_problem_count       integer not null default 0,
  mastery_proposal_count        integer not null default 0,

  -- The full itemized, already-prioritized evidence list (EvidenceItem[],
  -- priority_score descending) -- this is the actual payload Phase D-2 is
  -- expected to consume, not just a byproduct in `details`.
  items    jsonb not null default '[]'::jsonb,

  notes    text,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_evidence_bundles_run_at
  on public.sigmaris_evidence_bundles (run_at desc);

alter table public.sigmaris_evidence_bundles enable row level security;

create policy "service_role_only" on public.sigmaris_evidence_bundles
  using (auth.role() = 'service_role');
