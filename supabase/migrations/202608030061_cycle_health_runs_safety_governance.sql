-- Safety-3 (docs/sigmaris/safety_governance_report.md): adds safety-
-- governance coverage tracking to sigmaris_cycle_health_runs (Phase R-3,
-- 202607220048_cycle_health_runs.sql).
--
-- RC-1..RC-5 measure whether Sigmaris's own Experience->Memory->Temporal
-- Evaluation->Belief->Policy->Action loop is functioning. This is a
-- deliberately different domain -- whether newly added safety-critical
-- files (backend/app/services/safety_critical_files.py's registry) have
-- fallen out of sync with the actual codebase -- but Safety-3 integrates
-- it into the same measurement cadence/table for shared operator
-- visibility, per docs/sigmaris/safety_governance_report.md's Safety-3
-- section ("Phase RのRC-5との統合").
--
-- Unlike RC-5 (baseline-average-vs-current-value, needs >= 3 prior runs),
-- this check needs no history -- it's an instantaneous structural scan
-- (backend/app/services/safety_critical_files_scan.py::
-- find_unregistered_gate_files()) that can always be evaluated. There is
-- no "insufficient_history" equivalent state; hence the 2-value check
-- constraint below (healthy / gap_detected) rather than RC-5's 3-value
-- one.
--
-- safety_governance_status:
--   'healthy'       -- every heuristically-detected gate-pattern file is
--                       already present in SAFETY_CRITICAL_FILES
--   'gap_detected'  -- at least one gate-pattern file was found that is
--                       not yet registered (see safety_governance_
--                       unregistered_count, and details.safety_
--                       governance_unregistered_files for the actual
--                       paths + heuristic match reasons)
-- NULL means this run predates the Safety-3 rollout (older rows).
--
-- safety_governance_unregistered_count mirrors rc5_broke_metrics'
-- "headline in a column, detail in jsonb" split: the count alone is
-- enough for a quick SQL trend query ("has this been rising"), while the
-- actual file paths live in details.safety_governance_unregistered_files.

alter table public.sigmaris_cycle_health_runs
  add column if not exists safety_governance_status text
    check (safety_governance_status in ('healthy', 'gap_detected')),
  add column if not exists safety_governance_unregistered_count integer;

create index if not exists idx_sigmaris_cycle_health_runs_safety_governance_status
  on public.sigmaris_cycle_health_runs (safety_governance_status);
