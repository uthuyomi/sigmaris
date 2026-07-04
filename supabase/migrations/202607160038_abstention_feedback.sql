-- Phase B15: personalized abstention threshold.
--
-- Records how 海星さん reacted to a hedged (B11 low_confidence/no_evidence)
-- answer, classified from the very next user reply by abstention_feedback.
-- reflect_abstention_reaction() (fire-and-forget, mirrors A3/B2/B3/B6's
-- existing detection pattern — no response-path latency impact).
--
-- Same single-tenant, service-role-only table pattern as sigmaris_
-- decision_log/sigmaris_experience/sigmaris_topic_log/sigmaris_user_
-- preference_patterns: this is Sigmaris's own derived understanding of
-- 海星さん, not user-owned content, so no user_id column or per-user RLS.
--
-- One row per classified reaction (not an aggregate counter) — mirrors
-- decision_log.py's/topic_tracker.py's append-only-log style rather than
-- an incrementally-updated counter row, so the evidence trail stays
-- auditable and re-computable (get_threshold_adjustment() aggregates over
-- these rows at read time rather than trusting a running total that could
-- drift).

create table if not exists public.sigmaris_abstention_feedback (
  id            uuid primary key default gen_random_uuid(),
  reaction      text not null check (reaction in ('push_for_answer', 'supports_caution')),
  thread_id     uuid,
  invocation_id uuid,
  created_at    timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_abstention_feedback_created_at
  on public.sigmaris_abstention_feedback (created_at desc);

alter table public.sigmaris_abstention_feedback enable row level security;

create policy "service_role_only" on public.sigmaris_abstention_feedback
  using (auth.role() = 'service_role');
