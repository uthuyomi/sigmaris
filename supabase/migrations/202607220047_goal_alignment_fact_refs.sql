-- Phase R-1 (revised, docs/sigmaris/phase_r_report.md): close a gap found
-- while inventorying the existing "reference to the previous stage" links
-- each Experience->Memory->...->Policy stage already carries (B4's
-- thread_id/invocation_id, B2's source_experience_ids, A3's memory_refs,
-- B14's supporting_decision_ids, B9's source_table/source_id).
--
-- sigmaris_goal_alignment_flags (Policy Update, B16) already references its
-- evidence (decisions/topics) via evidence_refs (an id array), but its only
-- link back to the specific user_fact_items row(s) (category='goals') a
-- flag concerns is goal_reference — a free-text label the LLM invents from
-- that fact's key/value, used solely for de-duplicating across weekly runs
-- (goal_alignment.py's _upsert_flag(), matched by goal_reference string
-- equality). That label is not, and was never meant to be, a stable
-- pointer: the extraction prompt in goal_alignment.py never even shows the
-- LLM the goals' ids (only "key=... value=..."), so there was no way for a
-- flag to name the exact goal fact row it's about — unlike every other
-- stage pair in this system, which uses a real id or id array. This
-- migration adds that missing id-based reference; goal_reference is left
-- in place unchanged (still used for LLM-facing de-dup context and human-
-- readable display).

alter table public.sigmaris_goal_alignment_flags
  add column if not exists goal_fact_ids uuid[] not null default '{}';
