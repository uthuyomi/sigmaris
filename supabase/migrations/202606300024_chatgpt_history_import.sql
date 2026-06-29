-- Support importing historical ChatGPT conversations as time-aware memory.

alter table public.user_fact_items
  drop constraint if exists user_fact_items_category_check;

alter table public.user_fact_items
  add constraint user_fact_items_category_check
  check (category in (
    'profile', 'health', 'lifestyle', 'environment',
    'devices', 'preferences', 'preference', 'relationships', 'finance',
    'goals', 'work', 'personality', 'timeline'
  ));

alter table public.user_fact_items
  drop constraint if exists user_fact_items_source_check;

alter table public.user_fact_items
  add constraint user_fact_items_source_check
  check (source in ('manual', 'chat', 'sensor', 'import', 'chatgpt_import'));

alter table public.user_fact_history
  add column if not exists changed_at timestamptz;

alter table public.sigmaris_decision_log
  add column if not exists decided_at timestamptz,
  add column if not exists context text;

create or replace function public.set_fact_category_defaults()
returns trigger
language plpgsql
as $$
begin
  new.importance_score := case new.category
    when 'goals'         then 1.0
    when 'health'        then 0.9
    when 'profile'       then 0.8
    when 'relationships' then 0.8
    when 'finance'       then 0.7
    when 'work'          then 0.7
    when 'personality'   then 0.7
    when 'timeline'      then 0.7
    when 'lifestyle'     then 0.6
    when 'preferences'   then 0.5
    when 'preference'    then 0.5
    when 'devices'       then 0.4
    when 'environment'   then 0.4
    else 0.5
  end;

  new.privacy_level := case new.category
    when 'profile'       then 'private'
    when 'health'        then 'private'
    when 'finance'       then 'private'
    when 'relationships' then 'internal'
    when 'lifestyle'     then 'internal'
    when 'work'          then 'internal'
    when 'personality'   then 'internal'
    when 'timeline'      then 'internal'
    when 'goals'         then 'public'
    when 'preferences'   then 'public'
    when 'preference'    then 'public'
    when 'devices'       then 'public'
    when 'environment'   then 'public'
    else 'internal'
  end;

  return new;
end;
$$;
