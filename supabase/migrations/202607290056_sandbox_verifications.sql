-- Phase E-2 (docs/sigmaris/phase_e_report.md): persistence for the dynamic
-- sandbox verification pipeline, the second stage of the Phase E sandbox
-- rollout (A: static tests only [E-1] -> B: temporary-port dynamic testing
-- [E-2, this migration] -> C: Docker isolation [E-3, future]).
--
-- Computed by scripts/run_sandbox_verification.py -- one row per sandbox
-- SESSION (launch -> health-check -> guaranteed shutdown), not one row per
-- evaluated hypothesis. Unlike sigmaris_static_verifications (E-1, one row
-- per hypothesis), this pipeline never reads a hypothesis's content at all
-- -- it launches the CURRENT, UNMODIFIED Sigmaris codebase in an isolated
-- process and confirms the sandbox infrastructure itself (start / stop /
-- lightweight health checks) works safely. candidate_hypothesis_ids is a
-- purely informational jsonb array (the E-1 "insufficient_signal" hypothesis
-- ids this session's healthy sandbox could help a human manually verify
-- next) -- never used to drive any automated behavior in this table's
-- producing script.
--
-- IMPORTANT SAFETY PROPERTIES enforced by the producing code (see
-- sandbox_verification.py/sandbox_verification_runner.py for the actual
-- implementation, not enforced by this table):
--   - Refuses to launch on port 8000 (the documented production port)
--   - Binds only to 127.0.0.1 (not reachable outside this machine)
--   - Forces PROACTIVE_ENABLED/X_ENABLED/HEALTH_SYNC_ENABLED/
--     RESEARCH_ENABLED=false and blanks external credentials in the
--     subprocess's environment, regardless of the operator's real .env
--   - Reuses Phase C-full-1's dedicated Supabase Auth account pattern
--     (bench_auth.py) for the health checks it does run -- never touches
--     production user_fact_items/chat data
--   - Guarantees process termination via try/finally with a two-stage
--     terminate()-then-kill() shutdown, wrapped in an outer session-level
--     asyncio timeout as a second independent safety net
--
-- verdict follows the same "honest classification, not pass/fail"
-- philosophy as sigmaris_static_verifications.verdict:
--   "failed_to_start"          -- sandbox process never became reachable
--                                  within the startup timeout
--   "started_with_errors"      -- sandbox started, but at least one
--                                  lightweight health check raised an
--                                  unhandled exception (recorded, never
--                                  silently swallowed)
--   "started_but_checks_skipped" -- sandbox started, but the dedicated
--                                  bench Supabase account isn't configured
--                                  in this environment, so no health check
--                                  could actually run
--   "started_and_healthy"      -- sandbox started and all attempted health
--                                  checks completed without raising (NOT a
--                                  claim that any hypothesis is correct --
--                                  no hypothesis content was ever applied)
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_sandbox_verifications (
  id                        uuid primary key default gen_random_uuid(),
  run_at                    timestamptz not null default timezone('utc', now()),

  port                      integer not null,
  started                   boolean not null,
  startup_detail            text not null default '',
  terminated_cleanly        boolean not null,

  verdict                   text not null,
  health_checks             jsonb not null default '[]'::jsonb,

  -- Soft references (see rationale above -- intentionally no FK
  -- constraints) to the sigmaris_hypotheses rows this session's healthy
  -- sandbox pertains to (E-1's "insufficient_signal" list at the time of
  -- this run). Purely informational.
  candidate_hypothesis_ids  jsonb not null default '[]'::jsonb,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_sandbox_verifications_run_at
  on public.sigmaris_sandbox_verifications (run_at desc);

alter table public.sigmaris_sandbox_verifications enable row level security;

create policy "service_role_only" on public.sigmaris_sandbox_verifications
  using (auth.role() = 'service_role');
