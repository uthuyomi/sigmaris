-- Phase F-1 (docs/sigmaris/phase_f_report.md): persistence for generated
-- code-diff proposals -- the first (and, as of this migration, ONLY) place
-- in the entire Phase D/E/F lineage where an actual code change is
-- generated from a hypothesis.
--
-- =====================================================================
-- ABSOLUTE PRINCIPLE (repeated here because it governs this table's very
-- reason for existing): a row in this table is NEVER, under any
-- circumstance, automatically committed, branched, or turned into a pull
-- request. review_status is always created as 'pending' (or 'rejected' for
-- rows the mechanical safety check itself blocked, see below) and only a
-- human calling code_diff_proposal_store.py::record_review_decision() can
-- ever change it to 'approved'. No script, scheduler, or Runner in this
-- codebase writes to git, calls the GitHub API, or applies diff_text to
-- any file. Actually applying an approved proposal is explicitly out of
-- scope for Phase F-1 and reserved for a future, separately-designed
-- approval flow (task F-3).
-- =====================================================================
--
-- One row per generated proposal (one hypothesis -> at most one proposal
-- per run, since generation is scoped to a single target file per
-- hypothesis). Mirrors sigmaris_migration_review_queue's (Phase E-4)
-- review_status vocabulary and workflow exactly: pending/approved/rejected,
-- with review_notes/reviewed_by/reviewed_at recorded only on a human
-- decision.
--
-- safety_check_status classifies EVERY generated attempt, including ones
-- that never reach human review:
--   'passed'                    -- mechanical safety check found nothing
--                                  blocking; review_status='pending'
--   'blocked_sensitive_file'    -- diff touches a .env/credential/CI-CD/
--                                  dependency-manifest-style file (same
--                                  blocklist as the deleted self_
--                                  improvement.py); review_status='rejected'
--                                  automatically, never reaches a human
--   'blocked_safety_mechanism'  -- diff touches one of S-4's "last line of
--                                  defense" files (response_guard.py, B11,
--                                  constitution_guard.py, etc.);
--                                  review_status='rejected' automatically
--   'blocked_unexpected_target' -- the generated diff's own `+++ b/`
--                                  header(s) don't match the single file
--                                  the LLM was asked to change;
--                                  review_status='rejected' automatically
--   'generation_failed'         -- the LLM call failed, returned something
--                                  that didn't look like a diff, or the
--                                  target file was too large to safely
--                                  include in the prompt; review_status=
--                                  'rejected', diff_text is empty
--
-- IMPORTANT: rows with a 'blocked_*'/'generation_failed' safety_check_status
-- are kept for audit/transparency (task requirement: "生成されても、破棄
-- され、記録にのみ残す") but their review_status is pre-set to 'rejected'
-- at creation time (system-originated, not a human decision) -- they are
-- structurally excluded from get_pending_diff_proposals() and can never
-- proceed further.
--
-- hypothesis_id / hypothesis_priority_id / static_verification_id are soft
-- references (no FK constraints) -- same reasoning as every other Sigmaris
-- self-measurement/derived-data table in this lineage (D-1 through E-4):
-- never queried via join in the current design.
--
-- Same service_role_only, single-tenant pattern as the other Sigmaris
-- self-measurement tables: Sigmaris's own derived data, not user-owned
-- content.

create table if not exists public.sigmaris_code_diff_proposals (
  id                      uuid primary key default gen_random_uuid(),

  -- Soft references (see rationale above -- intentionally no FK
  -- constraints).
  hypothesis_id           uuid,
  hypothesis_priority_id  uuid,
  static_verification_id  uuid,

  title                   text not null,

  -- The module name (e.g. "response_guard") inferred by Phase E-1's
  -- static_verification.py::extract_candidate_modules() / matched_modules
  -- -- reused here as the target-file signal in place of Phase D-3's
  -- target_files, which is always NULL as of this migration (see
  -- code_diff_generation_runner.py's module docstring for the full
  -- rationale).
  target_module           text,
  target_file             text not null,

  -- The generated unified diff text. Empty string when safety_check_
  -- status='generation_failed'. NEVER applied to any file by any code in
  -- this codebase.
  diff_text               text not null default '',

  safety_check_status     text not null,
  safety_check_reason     text not null default '',

  -- "pending" | "approved" | "rejected" -- see the workflow description
  -- above. Only a human-invoked record_review_decision() call may write
  -- "approved" or "rejected" for a safety_check_status='passed' row;
  -- 'rejected' rows from a failed/blocked safety check are pre-set at
  -- creation time.
  review_status           text not null default 'pending',
  review_notes            text not null default '',
  reviewed_by             text,
  reviewed_at             timestamptz,

  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_code_diff_proposals_status
  on public.sigmaris_code_diff_proposals (review_status);

create index if not exists idx_sigmaris_code_diff_proposals_created_at
  on public.sigmaris_code_diff_proposals (created_at desc);

alter table public.sigmaris_code_diff_proposals enable row level security;

create policy "service_role_only" on public.sigmaris_code_diff_proposals
  using (auth.role() = 'service_role');
