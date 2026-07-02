-- Phase A3: sigmaris_decision_log goes from an unconditional per-turn log
-- ("chat_turn:xxxx") to recording actual decisions/policy changes, with
-- provenance (which thread/invocation produced the decision) and a
-- supersede chain (a new decision replaces an old one without deleting it).

alter table public.sigmaris_decision_log
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid,
  add column if not exists supersedes uuid references public.sigmaris_decision_log(id),
  add column if not exists superseded_by uuid references public.sigmaris_decision_log(id);

create index if not exists idx_sigmaris_decision_log_thread_id
  on public.sigmaris_decision_log (thread_id);

create index if not exists idx_sigmaris_decision_log_superseded_by
  on public.sigmaris_decision_log (superseded_by);

-- 'policy_change' covers "a decision or direction was established/changed
-- during a conversation" — distinct from the existing four types, which all
-- describe something *Sigmaris* did (proposed / refused / notified / acted),
-- not a decision reached in the conversation itself.
alter table public.sigmaris_decision_log
  drop constraint if exists sigmaris_decision_log_decision_type_check;
alter table public.sigmaris_decision_log
  add constraint sigmaris_decision_log_decision_type_check
  check (decision_type in ('proposal', 'refusal', 'notification', 'action', 'policy_change'));
