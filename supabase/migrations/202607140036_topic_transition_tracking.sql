-- Phase B6: topic transition tracking.
--
-- Deliberately simple, per the task's explicit instruction to avoid a
-- topic taxonomy or graph structure: a flat, append-only sequential log
-- of short LLM-generated labels. "Current topic" = the most recent row;
-- "previous topic" = the row before it. No explicit end/start range
-- columns — a topic's implicit duration is just "until the next row
-- appears", which is all topic_tracker.py's context injection needs.
--
-- Role vs. existing memory layers (see topic_tracker.py's module
-- docstring for the full comparison):
--   - Phase A1's cross-thread recent-log window: the raw conversation
--     itself (what was actually said).
--   - Phase B2's sigmaris_experience: durable "what happened" records,
--     independent of any one conversation.
--   - sigmaris_topic_log (this table): a lightweight running table-of-
--     contents for "what is being talked about right now", nothing more.
--
-- Like sigmaris_experience/sigmaris_decision_log/sigmaris_user_preference_
-- patterns, this is a single-tenant, service-role-only table with no
-- user_id column and no RLS policies (there is exactly one real user in
-- this system — see those tables' own migrations for the same pattern).
-- thread_id/invocation_id are provenance only (Phase B4 pattern), not a
-- partition key: topic continuity is meant to span threads, consistent
-- with Phase A1's cross-thread continuity design.

create table if not exists public.sigmaris_topic_log (
  id            uuid primary key default gen_random_uuid(),
  topic_label   text not null,
  thread_id     uuid,
  invocation_id uuid,
  created_at    timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_topic_log_created_at
  on public.sigmaris_topic_log (created_at desc);

alter table public.sigmaris_topic_log enable row level security;

create policy "service_role_only" on public.sigmaris_topic_log
  using (auth.role() = 'service_role');
