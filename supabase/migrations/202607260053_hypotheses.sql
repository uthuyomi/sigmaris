-- Phase D-2 (docs/sigmaris/phase_d_report.md): persistence for individual
-- improvement hypotheses generated from Phase D-1's prioritized evidence
-- (sigmaris_evidence_bundles.items). Computed by
-- scripts/run_hypothesis_generation.py -- one row per hypothesis, not one
-- row per generation run.
--
-- Deliberately a fine-grained log table (one hypothesis = one row) rather
-- than mirroring sigmaris_evidence_bundles'/sigmaris_grounding_health_runs'
-- "one run = one row, payload in jsonb" shape. This follows
-- sigmaris_citation_audit_log's (Phase G-4) precedent instead: individual
-- items are expected to be queried/filtered independently later (Phase D-3,
-- not yet implemented, is expected to prioritize/verify individual
-- hypotheses -- e.g. "show me only the ones flagged requires_special_
-- review"), which a single jsonb blob per run would make awkward.
--
-- evidence_bundle_id is a soft reference (no FK constraint to
-- sigmaris_evidence_bundles) -- same reasoning as sigmaris_citation_audit_
-- log's thread_id having no FK to chat_threads: these are Sigmaris's own
-- derived/measurement tables, not user-owned relational data, so the loose
-- coupling avoids migration-ordering and cross-table RLS complications for
-- a reference that is purely informational (traceability), never queried
-- via join in the current design.
--
-- IMPORTANT: this table only ever holds hypotheses that PASSED Phase D-2's
-- own filters (rule-based vague-hypothesis rejection + the Self-Critique-
-- style evidence-correspondence check). Rejected candidates are never
-- persisted here -- run_hypothesis_generation.py's own printed summary
-- (generated/filtered_vague/filtered_ungrounded/kept counts) is the only
-- record of rejection counts, not this table.
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_hypotheses (
  id                            uuid primary key default gen_random_uuid(),

  -- Soft reference to the sigmaris_evidence_bundles run this hypothesis was
  -- generated from (see rationale above -- intentionally no FK constraint).
  evidence_bundle_id            uuid,

  -- Which single EvidenceItem (from that bundle's `items` jsonb) this
  -- hypothesis was generated from -- kept denormalized here (rather than
  -- requiring a join + jsonb lookup into evidence_bundles) since this is
  -- exactly the traceability requirement ("仮説が根拠との対応関係を明確に
  --持つこと") the task asked for.
  source_evidence_category      text,
  source_evidence_title         text,
  evidence_priority_score       integer,

  title                         text not null,
  what_is_problem               text not null,
  why_problem                   text not null,
  how_to_improve                text not null,
  expected_metric_improvements  jsonb not null default '[]'::jsonb,

  -- Constitution (S-4) integration: true if either the rule-based keyword
  -- scan (hypothesis_generation.py::rule_based_safety_flag(), reusing S-4's
  -- own "last line of defense" inventory as its keyword source) OR the
  -- LLM's own self-reported touches_safety_mechanism field flagged this
  -- hypothesis as touching an existing safety mechanism. OR-combined,
  -- favoring recall over precision -- same pattern as Phase G-1's
  -- merge_llm_search_judgment().
  requires_special_review       boolean not null default false,
  safety_review_reason          text not null default '',

  details                       jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_hypotheses_created_at
  on public.sigmaris_hypotheses (created_at desc);

create index if not exists idx_sigmaris_hypotheses_requires_review
  on public.sigmaris_hypotheses (requires_special_review);

alter table public.sigmaris_hypotheses enable row level security;

create policy "service_role_only" on public.sigmaris_hypotheses
  using (auth.role() = 'service_role');
