-- Sigmaris memory layer expansion: confidence decay, logical deletion, trend tracking.

-- ─── user_fact_items: add new columns ────────────────────────────────────────

alter table public.user_fact_items
  add column if not exists is_stale         bool        not null default false,
  add column if not exists is_deleted       bool        not null default false,
  add column if not exists deleted_at       timestamptz,
  add column if not exists importance_score float       not null default 0.5
    check (importance_score >= 0.0 and importance_score <= 1.0),
  add column if not exists privacy_level    text        not null default 'internal'
    check (privacy_level in ('private', 'internal', 'public'));

create index if not exists idx_user_fact_items_active
  on public.user_fact_items (user_id, is_deleted, is_stale);

create index if not exists idx_user_fact_items_deleted_at
  on public.user_fact_items (deleted_at)
  where is_deleted = true;

-- Backfill importance_score for existing rows that still have the generic default.
update public.user_fact_items
set importance_score = case category
  when 'goals'         then 1.0
  when 'health'        then 0.9
  when 'profile'       then 0.8
  when 'relationships' then 0.8
  when 'finance'       then 0.7
  when 'lifestyle'     then 0.6
  when 'preferences'   then 0.5
  when 'devices'       then 0.4
  when 'environment'   then 0.4
  else 0.5
end
where importance_score = 0.5;

-- Backfill privacy_level for existing rows that still have the generic default.
update public.user_fact_items
set privacy_level = case category
  when 'profile'       then 'private'
  when 'health'        then 'private'
  when 'finance'       then 'private'
  when 'relationships' then 'internal'
  when 'lifestyle'     then 'internal'
  when 'goals'         then 'public'
  when 'preferences'   then 'public'
  when 'devices'       then 'public'
  when 'environment'   then 'public'
  else 'internal'
end
where privacy_level = 'internal';

-- ─── BEFORE INSERT trigger: category-based defaults ──────────────────────────
-- Runs before each INSERT so importance_score and privacy_level are always
-- derived from the row's category, regardless of what the caller passes.

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
    when 'lifestyle'     then 0.6
    when 'preferences'   then 0.5
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
    when 'goals'         then 'public'
    when 'preferences'   then 'public'
    when 'devices'       then 'public'
    when 'environment'   then 'public'
    else 'internal'
  end;

  return new;
end;
$$;

drop trigger if exists user_fact_items_category_defaults on public.user_fact_items;
create trigger user_fact_items_category_defaults
  before insert on public.user_fact_items
  for each row execute function public.set_fact_category_defaults();


-- ─── user_trend_items ─────────────────────────────────────────────────────────
-- Stores detected behavioural / lifestyle trends for a user.

create table if not exists public.user_trend_items (
  id                uuid        primary key default gen_random_uuid(),
  user_id           uuid        not null references auth.users(id) on delete cascade,
  category          text        not null
    check (category in ('lifestyle', 'health', 'work', 'mood', 'behavior')),
  trend_key         text        not null,
  trend_description text        not null,
  evidence          jsonb       not null default '[]'::jsonb,
  confidence        float       not null default 0.5
    check (confidence >= 0.0 and confidence <= 1.0),
  detected_at       timestamptz not null default timezone('utc', now()),
  last_updated_at   timestamptz not null default timezone('utc', now()),
  is_active         bool        not null default true,
  created_at        timestamptz not null default timezone('utc', now()),
  updated_at        timestamptz not null default timezone('utc', now()),
  unique (user_id, category, trend_key)
);

create index if not exists idx_user_trend_items_user_active
  on public.user_trend_items (user_id, is_active);

create trigger user_trend_items_updated_at
  before update on public.user_trend_items
  for each row execute function public.set_updated_at();

alter table public.user_trend_items enable row level security;

create policy "user_trend_items_select_own"
  on public.user_trend_items for select
  using (auth.uid() = user_id);

create policy "user_trend_items_insert_own"
  on public.user_trend_items for insert
  with check (auth.uid() = user_id);

create policy "user_trend_items_update_own"
  on public.user_trend_items for update
  using (auth.uid() = user_id);

create policy "user_trend_items_delete_own"
  on public.user_trend_items for delete
  using (auth.uid() = user_id);


-- ─── RPC: upsert_trend_item ──────────────────────────────────────────────────
-- Atomically upserts one trend item. Runs as the authenticated user (SECURITY
-- INVOKER) so RLS applies.

create or replace function public.upsert_trend_item(
  p_category          text,
  p_trend_key         text,
  p_trend_description text,
  p_evidence          jsonb,
  p_confidence        float
) returns jsonb
language plpgsql
security invoker
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_id      uuid;
  v_is_new  bool;
begin
  select id into v_id
  from   public.user_trend_items
  where  user_id   = v_user_id
    and  category  = p_category
    and  trend_key = p_trend_key;

  if v_id is not null then
    update public.user_trend_items
    set    trend_description = p_trend_description,
           evidence          = p_evidence,
           confidence        = p_confidence,
           last_updated_at   = timezone('utc', now()),
           is_active         = true,
           updated_at        = timezone('utc', now())
    where  id = v_id;
    v_is_new := false;
  else
    insert into public.user_trend_items
      (user_id, category, trend_key, trend_description, evidence, confidence)
    values
      (v_user_id, p_category, p_trend_key, p_trend_description, p_evidence, p_confidence)
    returning id into v_id;
    v_is_new := true;
  end if;

  return jsonb_build_object('id', v_id, 'is_new', v_is_new);
end;
$$;
