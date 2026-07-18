-- Self-2 (docs/sigmaris/self_awareness_report.md): persistence for the
-- Japanese, first-person capability summaries generated from Self-1's
-- capability_scan.py output (backend/app/services/capability_summary.py).
--
-- Deliberately a NEW table, not an extension of sigmaris_self_model.
-- sigmaris_self_model's identity_statement/current_goals/observed_patterns
-- are updated by self_model.py::reflect() analyzing audit-log BEHAVIOR over
-- time (a single evolving, version-bumped row) -- a fundamentally different
-- lifecycle from this table's rows, which are DERIVED FACTS re-computed
-- directly from a static scan of the codebase itself, independent of any
-- runtime behavior. Mixing the two would conflate "what I have learned about
-- my own behavior" with "what capabilities exist in my own source code" --
-- same reasoning phase_d_report.md's sigmaris_evidence_bundles migration
-- gives for staying separate from sigmaris_cycle_health_runs/sigmaris_
-- grounding_health_runs (different measurement family = different table).
-- This does follow self_model.py's own precedent of managing more than one
-- table for a related concern (sigmaris_self_model + sigmaris_self_
-- discrepancies already coexist in that same module).
--
-- One row per capability "domain" (a group of related files -- e.g. "私は
-- 記憶を検索・整理できる", covering B-group's ~15 files as one entry, per
-- the task's explicit "まとまりのある単位で要約する" requirement -- NOT
-- one row per source file). `domain` is UNIQUE so re-running the
-- summarizer overwrites the previous summary for that domain in place
-- (current-state semantics, like sigmaris_self_model's single-row-per-
-- version -- not an unbounded append-only history like sigmaris_cycle_
-- health_runs, since there is no meaningful "trend over time" for a
-- summary of static code; only the latest matters).
--
-- Same service_role_only, single-tenant pattern as every other Sigmaris
-- self-measurement table: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_capability_summaries (
  id                    uuid primary key default gen_random_uuid(),
  domain                text not null unique,

  -- The generated one-person, plain-Japanese description itself (2-3
  -- sentences, per the task's brevity requirement).
  summary_text          text not null,

  -- Headline counts (Self-1's raw candidate count for this domain, and
  -- Self-2's wiring-status breakdown -- see capability_summary.py's
  -- wiring-detection step). unwired_file_count > 0 means summary_text is
  -- expected to contain an explicit "not actually connected yet" caveat
  -- (the task's constraint 1 -- distinguish wired from unwired capabilities
  -- rather than silently presenting everything as equally live).
  file_count            integer not null default 0,
  wired_file_count      integer not null default 0,
  unwired_file_count    integer not null default 0,

  -- The actual relative file paths behind this domain's summary (posix
  -- form, repo-root-relative -- same format as capability_scan.py's
  -- CapabilityCandidate.relative_path), for traceability back to source
  -- when a human wants to verify what the summary is actually describing.
  source_files          jsonb not null default '[]'::jsonb,

  generated_at          timestamptz not null default timezone('utc', now()),
  created_at            timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_capability_summaries_domain
  on public.sigmaris_capability_summaries (domain);

alter table public.sigmaris_capability_summaries enable row level security;

create policy "service_role_only" on public.sigmaris_capability_summaries
  using (auth.role() = 'service_role');
