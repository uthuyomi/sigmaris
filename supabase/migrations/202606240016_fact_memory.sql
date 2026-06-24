-- Sigmaris fact memory layer: structured user knowledge with confidence, source, and history.

-- Reusable trigger function to auto-update updated_at (idempotent)
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := timezone('utc', now());
  return new;
end;
$$;


-- ─── user_fact_profile ────────────────────────────────────────────────────────
-- One row per user. Stores structured profile fields and JSONB blobs for
-- lifestyle, devices, preferences, goals, values, and communication settings.

create table if not exists public.user_fact_profile (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null unique references auth.users(id) on delete cascade,
  name                  text,
  birthdate             date,
  prefecture            text,
  city                  text,
  address_detail        text,
  email                 text,
  occupation            text,
  income_range          text,
  lifestyle_notes       jsonb,
  devices               jsonb,
  preferences           jsonb,
  goals                 jsonb,
  values                jsonb,
  communication_settings jsonb,
  created_at            timestamptz not null default timezone('utc', now()),
  updated_at            timestamptz not null default timezone('utc', now())
);

create trigger user_fact_profile_updated_at
  before update on public.user_fact_profile
  for each row execute function public.set_updated_at();

alter table public.user_fact_profile enable row level security;

create policy "user_fact_profile_select_own"
  on public.user_fact_profile for select
  using (auth.uid() = user_id);

create policy "user_fact_profile_insert_own"
  on public.user_fact_profile for insert
  with check (auth.uid() = user_id);

create policy "user_fact_profile_update_own"
  on public.user_fact_profile for update
  using (auth.uid() = user_id);


-- ─── user_fact_items ──────────────────────────────────────────────────────────
-- Individual fact items with confidence, source, and expiry.
-- One (user_id, category, key) tuple per row — unique constraint enables upsert.

create table if not exists public.user_fact_items (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  category    text not null check (category in (
                'profile', 'health', 'lifestyle', 'environment',
                'devices', 'preferences', 'relationships', 'finance', 'goals'
              )),
  key         text not null,
  value       text,
  confidence  float not null default 1.0 check (confidence >= 0.0 and confidence <= 1.0),
  source      text not null default 'manual' check (source in ('manual', 'chat', 'sensor', 'import')),
  notes       text,
  expires_at  timestamptz,
  created_at  timestamptz not null default timezone('utc', now()),
  updated_at  timestamptz not null default timezone('utc', now()),
  unique (user_id, category, key)
);

create index if not exists idx_user_fact_items_user_category
  on public.user_fact_items (user_id, category);

create index if not exists idx_user_fact_items_user_key
  on public.user_fact_items (user_id, key);

create trigger user_fact_items_updated_at
  before update on public.user_fact_items
  for each row execute function public.set_updated_at();

alter table public.user_fact_items enable row level security;

create policy "user_fact_items_select_own"
  on public.user_fact_items for select
  using (auth.uid() = user_id);

create policy "user_fact_items_insert_own"
  on public.user_fact_items for insert
  with check (auth.uid() = user_id);

create policy "user_fact_items_update_own"
  on public.user_fact_items for update
  using (auth.uid() = user_id);

create policy "user_fact_items_delete_own"
  on public.user_fact_items for delete
  using (auth.uid() = user_id);


-- ─── user_fact_history ────────────────────────────────────────────────────────
-- Immutable change log. No UPDATE or DELETE policies by design.

create table if not exists public.user_fact_history (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  fact_item_id  uuid not null references public.user_fact_items(id) on delete cascade,
  old_value     text,
  new_value     text,
  changed_by    text not null,
  reason        text,
  created_at    timestamptz not null default timezone('utc', now())
);

create index if not exists idx_user_fact_history_item_created_at
  on public.user_fact_history (fact_item_id, created_at desc);

create index if not exists idx_user_fact_history_user_created_at
  on public.user_fact_history (user_id, created_at desc);

alter table public.user_fact_history enable row level security;

create policy "user_fact_history_select_own"
  on public.user_fact_history for select
  using (auth.uid() = user_id);

create policy "user_fact_history_insert_own"
  on public.user_fact_history for insert
  with check (auth.uid() = user_id);

-- No UPDATE / DELETE policies: history is immutable.


-- ─── RPC: upsert_fact_item ────────────────────────────────────────────────────
-- Atomically upserts one fact item and appends a history row in the same
-- transaction. Runs as the authenticated user (SECURITY INVOKER) so RLS applies.

create or replace function public.upsert_fact_item(
  p_category  text,
  p_key       text,
  p_value     text,
  p_confidence float,
  p_source    text,
  p_reason    text,
  p_notes     text default null,
  p_expires_at timestamptz default null
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
      (user_id, category, key, value, confidence, source, notes, expires_at)
    values
      (v_user_id, p_category, p_key, p_value, p_confidence, p_source, p_notes, p_expires_at)
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
