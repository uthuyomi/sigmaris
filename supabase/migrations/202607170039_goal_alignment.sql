-- Phase B16: long-term goal alignment check.
--
-- Weekly batch (goal_alignment.extract_goal_alignment_flags(), scheduled
-- Sunday 4:35 — see proactive/scheduler.py) cross-references user_fact_
-- items' category='goals' facts (the primary, explicit source of 海星さん's
-- long-term goals — B17 already established these carry the highest fixed
-- importance_score, 1.0) against recent sigmaris_decision_log entries and
-- sigmaris_topic_log labels, looking for a *clearly and repeatedly*
-- evidenced drift, never a single instance (same principle as B14's
-- _MIN_SUPPORTING_DECISIONS).
--
-- Same service_role_only, single-tenant table pattern as sigmaris_
-- decision_log/sigmaris_experience/sigmaris_topic_log/sigmaris_user_
-- preference_patterns/sigmaris_abstention_feedback: this is Sigmaris's own
-- derived observation about 海星さん, not user-owned content.
--
-- Structurally mirrors sigmaris_user_preference_patterns (Phase B14) —
-- evidence_count + supporting refs that accumulate across weekly runs,
-- first_detected_at/last_confirmed_at for freshness display — plus one
-- addition specific to this phase: last_surfaced_at, so the response path
-- can rate-limit how often a flag is offered to the model as something it
-- *may* mention (requirement: don't nag). last_surfaced_at is updated
-- fire-and-forget from orchestrator's existing background cognitive layer,
-- never synchronously on the response path (see phase_b16_report.md
-- section 3).

create table if not exists public.sigmaris_goal_alignment_flags (
  id                       uuid primary key default gen_random_uuid(),
  goal_reference           text not null,
  flag_statement           text not null,
  evidence_refs            jsonb not null default '[]'::jsonb,
  evidence_count           integer not null default 0,
  first_detected_at        timestamptz not null default timezone('utc', now()),
  last_confirmed_at        timestamptz not null default timezone('utc', now()),
  last_analyzed_decision_count integer not null default 0,
  last_surfaced_at         timestamptz,
  created_at               timestamptz not null default timezone('utc', now()),
  updated_at               timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_goal_alignment_flags_evidence
  on public.sigmaris_goal_alignment_flags (evidence_count desc);

alter table public.sigmaris_goal_alignment_flags enable row level security;

create policy "service_role_only" on public.sigmaris_goal_alignment_flags
  using (auth.role() = 'service_role');

-- Reuses the shared trigger function from 202606240016_fact_memory.sql.
create trigger trg_sigmaris_goal_alignment_flags_updated_at
  before update on public.sigmaris_goal_alignment_flags
  for each row execute function public.set_updated_at();
