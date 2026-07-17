-- Phase F-2 (docs/sigmaris/phase_f_report.md): adds verification_tier
-- tracking to sigmaris_code_diff_proposals (Phase F-1,
-- 202607310058_code_diff_proposals.sql -- not yet applied as of this
-- migration, per this project's established "create migrations only,
-- application is the operator's decision" policy; kept as a separate
-- additive migration rather than editing the F-1 migration file directly,
-- matching this codebase's consistent practice of never modifying an
-- already-committed migration file).
--
-- F-1 only ever generated diff proposals from hypotheses E-1 rated
-- "baseline_healthy_with_coverage" (real, content-specific test coverage).
-- F-2 widened that pool to also include hypotheses E-1 rated
-- "insufficient_signal" PROVIDED the most recent Phase E-2 sandbox session
-- proved the sandbox infrastructure itself starts/stops cleanly --
-- see hypothesis_verification.py::classify_verification_tier().
--
-- verification_tier records, for every row (both old and new candidates),
-- which of the two tiers backed this specific proposal:
--   'hypothesis_verified_coverage'             -- E-1 confirmed existing
--                                                  test coverage for this
--                                                  hypothesis's own target
--                                                  area (content-specific
--                                                  signal)
--   'sandbox_infra_available_unverified_content' -- no existing coverage
--                                                  for this hypothesis;
--                                                  only the general sandbox
--                                                  environment (E-2) was
--                                                  proven healthy. This is
--                                                  NOT a claim that the
--                                                  hypothesis's content was
--                                                  validated in any way --
--                                                  see hypothesis_
--                                                  verification.py's module
--                                                  docstring for the full
--                                                  rationale behind this
--                                                  distinction.
-- verification_tier_reason carries the human-readable explanation
-- (classify_verification_tier()'s own `reason` field) so a reviewer never
-- has to guess why a given proposal landed in one tier or the other.

alter table public.sigmaris_code_diff_proposals
  add column if not exists verification_tier text,
  add column if not exists verification_tier_reason text not null default '';

create index if not exists idx_sigmaris_code_diff_proposals_verification_tier
  on public.sigmaris_code_diff_proposals (verification_tier);
