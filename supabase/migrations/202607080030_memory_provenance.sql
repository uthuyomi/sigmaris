-- Phase B4: memory provenance tracking.
--
-- Phase A3 (202607040026_decision_log_supersede.sql) already added
-- thread_id/invocation_id to sigmaris_decision_log and decision_log.py
-- already populates them correctly on write (verified in
-- phase_b4_report.md section 1 — no code change needed there). This
-- migration extends the same pattern to the other two memory tables so all
-- three consistently record which conversation/turn a record originated
-- from: user_fact_items (facts extracted by memory_extractor.py) and
-- sigmaris_experience (records via /agent/experience/record).
--
-- Existing rows are left untouched (thread_id/invocation_id NULL) — no
-- retroactive backfill, per this task's explicit scope.

alter table public.user_fact_items
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid;

create index if not exists idx_user_fact_items_thread_id
  on public.user_fact_items (thread_id);

alter table public.sigmaris_experience
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid;

create index if not exists idx_sigmaris_experience_thread_id
  on public.sigmaris_experience (thread_id);

-- upsert_fact_item(): accept optional provenance. Set only on the INSERT
-- branch — provenance should reflect where a fact was first created, not
-- be overwritten every time a later conversation re-confirms/updates the
-- same (user_id, category, key) row.
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
  p_invocation_id uuid default null
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
           updated_at  = timezone('utc', now())
    where  id = v_item_id;
  else
    insert into public.user_fact_items
      (user_id, category, key, value, confidence, source, notes, expires_at, thread_id, invocation_id)
    values
      (v_user_id, p_category, p_key, p_value, p_confidence, p_source, p_notes, p_expires_at, p_thread_id, p_invocation_id)
    returning id into v_item_id;
    v_old_value := null;
  end if;

  insert into public.user_fact_history
    (user_id, fact_item_id, old_value, new_value, changed_by, reason)
  values
    (v_user_id, v_item_id, v_old_value, p_value, p_source, p_reason);

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
