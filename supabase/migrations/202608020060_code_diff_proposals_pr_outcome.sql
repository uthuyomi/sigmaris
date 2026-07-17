-- Phase F-3 (docs/sigmaris/phase_f_report.md): adds PR-creation outcome
-- tracking to sigmaris_code_diff_proposals (Phase F-1,
-- 202607310058_code_diff_proposals.sql; Phase F-2,
-- 202608010059_code_diff_proposals_verification_tier.sql -- not yet
-- applied as of this migration, per this project's established "create
-- migrations only, application is the operator's decision" policy; kept
-- as a separate additive migration rather than editing the F-1/F-2
-- migration files directly).
--
-- review_status (F-1) records WHETHER a human approved or rejected a
-- proposal. This migration adds separate columns recording WHAT
-- HAPPENED as a result of an approval -- these are intentionally kept
-- distinct from review_status so that "the human approved X" and
-- "the system actually reached GitHub for X" are never conflated. In
-- particular, diff_approval.py's post-approval Constitution re-check
-- (gate B) can fail AFTER review_status is already "approved" -- in
-- that case review_status stays "approved" (an honest record of what
-- the human decided) while pr_creation_status separately records
-- "blocked_by_constitution_recheck" (an honest record that the system
-- refused to act on it). See diff_approval.py's module docstring.
--
-- pr_creation_status values:
--   'pr_created'                       -- succeeded; pr_url/pr_branch set
--   'skipped_not_configured'           -- SIGMARIS_PR_GITHUB_TOKEN/REPO unset
--   'blocked'                          -- 3rd defensive safety re-check failed
--   'skipped_daily_limit'              -- _MAX_DAILY_PRS reached
--   'blocked_by_constitution_recheck'  -- gate B failed after approval recorded
--   'failed'                           -- GitHub API error, or diff no longer
--                                          applies cleanly (DiffApplyError)
-- NULL means no approval/execution attempt has happened yet for this row
-- (still pending, or was rejected -- rejected rows never reach this code
-- path at all, per diff_approval.py::reject_diff_proposal()).

alter table public.sigmaris_code_diff_proposals
  add column if not exists pr_creation_status text,
  add column if not exists pr_url text not null default '',
  add column if not exists pr_branch text not null default '',
  add column if not exists pr_creation_error text not null default '';

create index if not exists idx_sigmaris_code_diff_proposals_pr_creation_status
  on public.sigmaris_code_diff_proposals (pr_creation_status);
