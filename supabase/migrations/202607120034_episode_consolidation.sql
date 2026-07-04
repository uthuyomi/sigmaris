-- Phase B2: episodic/semantic memory separation.
--
-- sigmaris_experience (episodic): "what happened at a point in time" —
-- populated per-turn now via experience_layer.detect_and_record_episode(),
-- called from orchestrator/service.py's _cognitive_layer_bg fire-and-forget
-- task alongside Phase A3's decision detection. Before this phase,
-- sigmaris_experience had thread_id/invocation_id columns ready (Phase B4)
-- but no caller in the normal chat flow ever wrote to it — see
-- phase_b4_report.md section 1 and phase_b2_report.md section 1.
--
-- user_fact_items (semantic): "what is permanently true" — unchanged in
-- shape, but can now also be populated by the weekly consolidation job
-- (experience_layer.consolidate_episodic_memory()), which promotes
-- recurring (or, exceptionally, single but clearly-permanent) patterns
-- found across sigmaris_experience rows. source_experience_ids records
-- which episodic records a promoted fact came from — the Phase B4
-- provenance pattern (thread_id/invocation_id) records *where in the
-- conversation* a fact was first created, this records *which memories it
-- was derived from*, which is a distinct kind of provenance only
-- consolidation-derived facts have.

alter table public.user_fact_items
  drop constraint if exists user_fact_items_source_check;

alter table public.user_fact_items
  add constraint user_fact_items_source_check
  check (source in ('manual', 'chat', 'sensor', 'import', 'chatgpt_import', 'episode_consolidation'));

alter table public.user_fact_items
  add column if not exists source_experience_ids uuid[];

-- upsert_fact_item(): accept optional source_experience_ids, same
-- insert-only-provenance pattern as thread_id/invocation_id
-- (202607080030_memory_provenance.sql) — set only when this call creates a
-- *new* row, never overwritten on a later update of the same
-- (user_id, category, key). A plain CREATE OR REPLACE is sufficient here
-- (unlike the search RPCs elsewhere in this project) because this function
-- returns jsonb, not a fixed RETURNS TABLE column list, so appending a new
-- trailing default parameter doesn't require a DROP first.
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
