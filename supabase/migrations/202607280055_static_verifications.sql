-- Phase E-1 (docs/sigmaris/phase_e_report.md): persistence for the static
-- verification pipeline, the first stage of the Phase E sandbox rollout
-- (A: static tests only -> B: temporary-port dynamic testing -> C: Docker
-- isolation, per phase_e_report.md's staged recommendation).
--
-- Computed by scripts/run_static_verification.py -- one row per evaluated
-- hypothesis per run, not one row per run. IMPORTANT: this pipeline never
-- modifies application code. It only (a) runs the EXISTING, unmodified
-- backend/tests/ suite as a subprocess baseline check, and (b) statically
-- parses backend/tests/*.py import statements (ast.parse, no execution) to
-- see whether any existing test covers the module(s) a hypothesis appears
-- to target. No hypothesis-derived code is ever written or executed.
--
-- Deliberately a NEW table, mirroring sigmaris_hypothesis_priorities'
-- (Phase D-3) shape: hypothesis_priority_id is a soft reference (no FK
-- constraint) to sigmaris_hypothesis_priorities.id -- the specific
-- prioritization-run row this verification extends -- with hypothesis_id
-- (sigmaris_hypotheses.id) denormalized alongside it for convenience, same
-- reasoning as every other Sigmaris self-measurement table in this lineage
-- (D-1/D-2/D-3): never queried via join in the current design.
--
-- verdict is intentionally a 3-way, epistemically honest classification
-- rather than pass/fail -- see static_verification.py's module docstring
-- for why a non-executing static check cannot honestly claim "pass" or
-- "fail" in the way a real dynamic test run could:
--   "excluded_migration"            -- kept out of this pipeline entirely,
--                                       per phase_e_report.md 3.2's
--                                       recommendation (migrations require
--                                       mandatory human review, not
--                                       automated verification)
--   "baseline_unhealthy"            -- backend/tests/ itself is currently
--                                       failing; no per-hypothesis signal
--                                       can be trusted
--   "insufficient_signal"           -- baseline passes, but no existing
--                                       test was found covering the area
--                                       this hypothesis appears to target
--   "baseline_healthy_with_coverage" -- baseline passes AND at least one
--                                       matched module has existing test
--                                       coverage (still not a guarantee
--                                       the hypothesis itself is correct)
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_static_verifications (
  id                     uuid primary key default gen_random_uuid(),
  run_at                 timestamptz not null default timezone('utc', now()),

  -- Soft references (see rationale above -- intentionally no FK
  -- constraints).
  hypothesis_priority_id uuid,
  hypothesis_id          uuid,

  verdict                text not null,
  matched_modules        jsonb not null default '[]'::jsonb,
  reason                 text not null default '',

  -- The baseline (backend/tests/) result is the SAME for every row within
  -- one run_at (one subprocess pytest invocation per run, shared across
  -- all evaluated hypotheses) -- denormalized onto each row rather than a
  -- separate baseline table, since a run's hypothesis count is small
  -- (single digits to low tens) and this keeps the "1 row = 1 evaluated
  -- hypothesis" shape consistent with sigmaris_hypotheses/sigmaris_
  -- hypothesis_priorities.
  baseline_passed        boolean not null,
  baseline_summary       text not null default '',

  details                jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_static_verifications_run_at
  on public.sigmaris_static_verifications (run_at desc);

create index if not exists idx_sigmaris_static_verifications_verdict
  on public.sigmaris_static_verifications (verdict);

alter table public.sigmaris_static_verifications enable row level security;

create policy "service_role_only" on public.sigmaris_static_verifications
  using (auth.role() = 'service_role');
