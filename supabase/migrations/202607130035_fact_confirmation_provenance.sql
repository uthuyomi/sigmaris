-- Phase B3: memory self-verification loop.
--
-- active_inquiry.get_inquiry_question() can now ask the user to re-confirm
-- an existing low-confidence/stale/long-unconfirmed user_fact_items row
-- (not just fill a missing one), and reflect_pending_confirmation()
-- writes the user's reply back via upsert_fact_item(). That write is
-- always an UPDATE (the fact already exists by definition — a
-- confirmation candidate is never a null field), and Phase B4's
-- thread_id/invocation_id on user_fact_items itself are documented as
-- insert-only ("records where a fact was first generated, not who last
-- touched it" — 202607080030_memory_provenance.sql). That's the right
-- behavior for user_fact_items, but it means there was previously no way
-- to record *which conversation caused a later update* at all — not even
-- for ordinary memory_extractor.py re-upserts, let alone this new
-- confirmation flow. user_fact_history already logs every change
-- (old_value/new_value/changed_by/reason) but had no thread_id/
-- invocation_id columns to say *from which conversation*.
--
-- This migration closes that gap the other direction from B4: the history
-- row (not the fact row) now always carries thread_id/invocation_id,
-- updated on every call (insert or update branch) since a history row
-- represents one specific event, not "where first created".
--
-- Also: the update branch now clears is_stale — any call through this RPC
-- represents 海星さん/a code path actively re-asserting the fact's value,
-- which is exactly the situation the contradiction-flagging in
-- memory_validator.py's is_stale is meant to be resolved by. Previously
-- there was no way to un-flag a contradiction-flagged fact at all short of
-- it being logically deleted by the importance x confidence threshold.

alter table public.user_fact_history
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid;

create index if not exists idx_user_fact_history_thread_id
  on public.user_fact_history (thread_id);

create or replace function public.upsert_fact_item(
  p_category  text,
  p_key       text,
  p_value     text,
  p_confidence float,
  p_source    text,
  p_reason    text,
  p_notes     text default null,
  p_expires_at timestamptz default null,
  p_thread_id uuid default null,
  p_invocation_id uuid default null,
  p_source_experience_ids uuid[] default null
) returns jsonb
language plpgsql
security invoker
set search_path = public, auth
as $$
declare
  v_user_id    uuid := auth.uid();
  v_existing_id uuid;
  v_old_value  text;
  v_item_id    uuid;
begin
  select id, value
  into   v_existing_id, v_old_value
  from   public.user_fact_items
  where  user_id  = v_user_id
    and  category = p_category
    and  key      = p_key;

  if v_existing_id is not null then
    v_item_id := v_existing_id;
    update public.user_fact_items
    set    value       = p_value,
           confidence  = p_confidence,
           source      = p_source,
           notes       = coalesce(p_notes, notes),
           expires_at  = p_expires_at,
           is_stale    = false,
           updated_at  = timezone('utc', now())
    where  id = v_item_id;
  else
    insert into public.user_fact_items
      (user_id, category, key, value, confidence, source, notes, expires_at,
       thread_id, invocation_id, source_experience_ids)
    values
      (v_user_id, p_category, p_key, p_value, p_confidence, p_source, p_notes, p_expires_at,
       p_thread_id, p_invocation_id, p_source_experience_ids)
    returning id into v_item_id;
    v_old_value := null;
  end if;

  insert into public.user_fact_history
    (user_id, fact_item_id, old_value, new_value, changed_by, reason, thread_id, invocation_id)
  values
    (v_user_id, v_item_id, v_old_value, p_value, p_source, p_reason, p_thread_id, p_invocation_id);

  return jsonb_build_object(
    'id',       v_item_id,
    'category', p_category,
    'key',      p_key,
    'value',    p_value,
    'old_value', v_old_value,
    'is_new',   v_existing_id is null
  );
end;
$$;
