-- Phase G-5 (docs/sigmaris/phase_g_report.md): persistence for periodic
-- Grounding-health measurement runs (Citation Precision / Search Trigger
-- Rate / Contradiction Rate), computed by scripts/run_grounding_health.py
-- from sigmaris_citation_audit_log (G-4) + chat_messages -- no new data
-- collection was added for this table; it only records the result of
-- each periodic aggregation run.
--
-- Mirrors sigmaris_cycle_health_runs' shape (Phase R-3) deliberately:
-- one row per CLI invocation, headline scores promoted to real float
-- columns (so "how has citation_precision trended" is a plain SQL query),
-- everything else in `details` jsonb. Kept as a SEPARATE table from
-- sigmaris_cycle_health_runs and sigmaris_eval_runs (C-mini/C-full) --
-- same reasoning as cycle_health_runs' own migration comment: Grounding
-- metrics (search/citation quality) measure a different concern than
-- cycle health (Experience->Memory->...->Action loop integrity) or eval
-- runs (memory retrieval accuracy). Mixing metric families into one table
-- makes "which family does this row belong to" ambiguous at read time.
--
-- Same service_role_only, single-tenant pattern as sigmaris_cycle_health_
-- runs/sigmaris_citation_audit_log/sigmaris_decision_log: Sigmaris's own
-- derived measurement data, not user-owned content.

create table if not exists public.sigmaris_grounding_health_runs (
  id                    uuid primary key default gen_random_uuid(),
  run_at                timestamptz not null default timezone('utc', now()),
  window_days           integer not null,
  period_from           timestamptz,
  period_to             timestamptz,

  -- Citation Precision: faithful / (faithful + distorted), among claims
  -- that were actually referenced in a response (not_used excluded).
  citation_precision           float,
  citation_precision_faithful  integer,
  citation_precision_distorted integer,

  -- Search Trigger Rate: turns with a citation-audit record (a lower-
  -- bound proxy for needs_search=true, see phase_g_report.md Phase G-5
  -- 2.2節 for why this is an approximation, not an exact count) / total
  -- assistant turns in the window.
  search_trigger_rate          float,
  search_trigger_audited_turns integer,
  search_trigger_total_turns   integer,

  -- Contradiction Rate: turns (among audited turns) where G-3 flagged a
  -- non-"no_contradiction" verdict, or G-4 flagged any "distorted" claim.
  contradiction_rate           float,
  contradiction_flagged_turns  integer,
  contradiction_audited_turns  integer,

  notes    text,
  details  jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_grounding_health_runs_run_at
  on public.sigmaris_grounding_health_runs (run_at desc);

alter table public.sigmaris_grounding_health_runs enable row level security;

create policy "service_role_only" on public.sigmaris_grounding_health_runs
  using (auth.role() = 'service_role');
