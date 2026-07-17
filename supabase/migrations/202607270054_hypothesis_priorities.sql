-- Phase D-3 (docs/sigmaris/phase_d_report.md): persistence for
-- prioritization + verifiability-assessment runs over Phase D-2's
-- hypotheses (sigmaris_hypotheses). Computed by
-- scripts/run_hypothesis_prioritization.py -- one row per hypothesis per
-- run, not one row per run.
--
-- Deliberately a NEW table rather than adding columns to sigmaris_
-- hypotheses and UPDATE-ing them in place. sigmaris_hypotheses (like
-- sigmaris_citation_audit_log before it) is treated as an immutable,
-- append-only record of what D-2 generated; prioritization is a separate,
-- re-runnable EVALUATION of that snapshot, not a mutation of the original
-- hypothesis. This also means a hypothesis can be re-evaluated later
-- (e.g. after the verifiable-metric vocabulary in hypothesis_
-- prioritization.py is extended) without destroying the prior run's
-- result -- same reasoning that already justified sigmaris_hypotheses'
-- own granular-log shape over sigmaris_evidence_bundles' aggregate shape.
--
-- hypothesis_id is a soft reference (no FK constraint) -- same reasoning
-- as sigmaris_hypotheses.evidence_bundle_id: Sigmaris's own derived
-- measurement data, never queried via join in the current design.
--
-- IMPORTANT: special_review-track rows always have priority_rank = NULL
-- and phase_e_handoff = NULL. This is intentional, not a missing-data gap
-- -- Phase D-2's requires_special_review hypotheses are explicitly kept
-- out of competitive ranking and out of the Phase E handoff payload,
-- pending human review (task requirement 2).
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_hypothesis_priorities (
  id                              uuid primary key default gen_random_uuid(),
  run_at                          timestamptz not null default timezone('utc', now()),

  -- Soft reference to the sigmaris_hypotheses row this evaluation covers
  -- (see rationale above -- intentionally no FK constraint).
  hypothesis_id                   uuid,

  -- "normal" | "special_review" -- see hypothesis_prioritization.py::
  -- prioritize_hypotheses(). The two tracks are never ranked against each
  -- other.
  track                           text not null,

  -- NULL for track='special_review' (not competitively ranked). 1-based,
  -- unique within (run_at, track='normal').
  priority_rank                   integer,

  -- evidence_priority_score (Phase D-1 origin) + a capped bonus for how
  -- many known-measurable metrics the hypothesis names (Phase D-2 origin
  -- signal) -- see hypothesis_prioritization.py::compute_priority_score()
  -- for the exact (deliberately simple, non-ML) formula.
  priority_score                  integer not null,

  -- Verifiability assessment: does expected_metric_improvements name a
  -- known, measurable metric (RC-1..RC-5 / Citation Precision / Search
  -- Trigger Rate / Contradiction Rate / memory_precision / etc.), or is
  -- the prediction too vague to check against a test result later.
  verifiability_checkable         boolean not null,
  verifiability_matched_metrics   jsonb not null default '[]'::jsonb,
  verifiability_reason            text not null default '',

  -- The full Phase E hand-off payload (hypothesis_prioritization.py::
  -- build_phase_e_handoff()) for track='normal' rows; NULL for
  -- track='special_review' rows (see note above). Phase E itself is not
  -- implemented by this migration/table -- this column only records the
  -- DESIGNED hand-off shape for the next phase to consume.
  phase_e_handoff                 jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_hypothesis_priorities_run_at
  on public.sigmaris_hypothesis_priorities (run_at desc);

create index if not exists idx_sigmaris_hypothesis_priorities_track
  on public.sigmaris_hypothesis_priorities (track);

alter table public.sigmaris_hypothesis_priorities enable row level security;

create policy "service_role_only" on public.sigmaris_hypothesis_priorities
  using (auth.role() = 'service_role');
