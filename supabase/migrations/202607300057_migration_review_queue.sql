-- Phase E-4 (docs/sigmaris/phase_e_report.md): persistence for the
-- migration-review queue -- the formal human-review workflow for
-- hypotheses that E-1's static_verification.py::mentions_migration()
-- flagged as "excluded_migration" (a DB schema change is implied) and
-- therefore kept out of both E-1's static checks and E-2's dynamic
-- sandbox checks entirely.
--
-- IMPORTANT: this table is NOT an automation mechanism. No script ever
-- transitions a row's review_status automatically -- "pending" is the only
-- status any producing script writes; "approved"/"rejected" are written
-- exclusively by a human calling migration_review_queue_store.py::
-- record_review_decision() (see that function's docstring). This
-- deliberately avoids the "over-automation" the task explicitly warned
-- against: the goal is a clear, auditable human workflow, not automatic
-- migration approval.
--
-- One row per hypothesis (not per queue-building run) -- mirrors sigmaris_
-- hypotheses'/sigmaris_static_verifications' "one row per item" shape.
-- Deduplicated at write time by migration_review_queue_runner.py (a
-- hypothesis already present in this table, regardless of status, is never
-- re-queued) so repeated E-1/E-4 runs don't spam duplicate entries for a
-- hypothesis that keeps resurfacing at the top of D-3's priority list.
--
-- hypothesis_id / hypothesis_priority_id / static_verification_id are soft
-- references (no FK constraints) -- same reasoning as every other Sigmaris
-- self-measurement/derived-data table in this lineage (D-1 through E-2):
-- never queried via join in the current design.
--
-- title/what_is_problem/why_problem/how_to_improve/source_evidence/
-- expected_metric_improvements are copied from Phase D-3's phase_e_handoff
-- payload (hypothesis_prioritization.py::build_phase_e_handoff()) rather
-- than re-fetched from sigmaris_hypotheses -- that payload already
-- aggregates everything a human reviewer needs, by design (Phase D-3
-- report section 20).
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_migration_review_queue (
  id                            uuid primary key default gen_random_uuid(),

  -- Soft references (see rationale above -- intentionally no FK
  -- constraints).
  hypothesis_id                 uuid,
  hypothesis_priority_id        uuid,
  static_verification_id        uuid,

  title                         text not null,
  what_is_problem               text not null,
  why_problem                   text not null,
  how_to_improve                text not null,

  -- Why E-1's static_verification.py::mentions_migration() flagged this
  -- hypothesis (the matched keyword and a one-line explanation).
  migration_reason              text not null default '',

  source_evidence               jsonb not null default '{}'::jsonb,
  expected_metric_improvements  jsonb not null default '[]'::jsonb,

  -- Phase D-3's own ranking context, carried through for the human
  -- reviewer's reference (NOT used to auto-prioritize review order by any
  -- script in this codebase).
  d3_priority_rank               integer,
  d3_priority_score              integer,

  -- "pending" | "approved" | "rejected" -- see migration_review_queue.py::
  -- REVIEW_STATUSES. Always created as "pending"; only a human-invoked
  -- call to record_review_decision() may change it.
  review_status                 text not null default 'pending',
  review_notes                  text not null default '',
  reviewed_by                   text,
  reviewed_at                   timestamptz,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_migration_review_queue_status
  on public.sigmaris_migration_review_queue (review_status);

create index if not exists idx_sigmaris_migration_review_queue_created_at
  on public.sigmaris_migration_review_queue (created_at desc);

alter table public.sigmaris_migration_review_queue enable row level security;

create policy "service_role_only" on public.sigmaris_migration_review_queue
  using (auth.role() = 'service_role');
