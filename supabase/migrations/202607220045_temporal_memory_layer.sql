-- Temporal Layer Step 1: memory_kind classification + bi-temporal state facts.
--
-- Problem this addresses (海星さん's report): Sigmaris re-reports days-old
-- events as if they just happened. The content was accurate, but nothing
-- distinguished "a one-off thing that happened" (event) from "a standing
-- fact that stays true until replaced" (state) from "a judgment tendency"
-- (trait, already B14's domain) — so all three decayed/aged identically.
--
-- Approach (bi-temporal, per Zep/Graphiti's "invalidate, never delete"
-- pattern, arXiv:2501.13956, scoped down to what a single new column +
-- one self-referencing FK can express — no graph DB, no new table):
--   - event:  decays faster (TTL-like, see memory_validator.py) regardless
--             of category — a one-off thing fades whether or not its
--             *category* happens to be slow-decaying.
--   - state:  gets valid_from (when it became true in the real world, best
--             guess) and superseded_by (self-FK to the row that replaced
--             it when a contradicting state fact arrives — the old row is
--             never deleted, only marked superseded, exactly mirroring
--             sigmaris_decision_log's existing supersede pattern from
--             Phase A3/202607040026_decision_log_supersede.sql).
--   - trait:  unchanged behavior — B14 already owns this concept
--             (sigmaris_user_preference_patterns); memory_kind='trait' on
--             user_fact_items is a label only, no new logic keys off it.
--   - NULL:   every existing row, and any future row a caller doesn't
--             classify — behaves exactly as before this migration (no
--             retroactive classification, per this task's explicit scope).

alter table public.user_fact_items
  add column if not exists memory_kind text check (memory_kind in ('event', 'state', 'trait')),
  add column if not exists valid_from  timestamptz,
  add column if not exists superseded_by uuid references public.user_fact_items(id);

create index if not exists idx_user_fact_items_memory_kind
  on public.user_fact_items (memory_kind);

create index if not exists idx_user_fact_items_superseded_by
  on public.user_fact_items (superseded_by);

-- ─── Relax (user_id, category, key) uniqueness to "one ACTIVE row" ────────────
--
-- The original table-level `unique (user_id, category, key)` constraint
-- (202606240016_fact_memory.sql) enforces uniqueness across *all* rows,
-- superseded or not — which makes "insert a new state row under the same
-- (category, key), keep the old one" structurally impossible as long as
-- that constraint exists. A partial unique index (active rows only, i.e.
-- superseded_by is null) is the standard Postgres pattern for exactly this
-- "soft-versioned natural key" shape, and is what this migration switches
-- to. The DROP CONSTRAINT below assumes Postgres's default auto-generated
-- name for an unnamed multi-column table-level UNIQUE constraint
-- (`<table>_<col1>_<col2>_<col3>_key`) — this matches the naming already
-- visible on this same table's single-column CHECK constraints
-- (user_fact_items_category_check, user_fact_items_source_check, both
-- `<table>_<col>_check`). DROP CONSTRAINT IF EXISTS is a safe no-op if this
-- name assumption is wrong, but if so the old constraint would remain in
-- place, silently blocking any state-supersede insert with a duplicate-key
-- error (caught and logged by the calling Python code, not a corruption
-- risk, but the feature would silently not work) — see
-- docs/sigmaris/temporal_layer_report.md for the operator verification
-- query to confirm this step actually took effect.

alter table public.user_fact_items
  drop constraint if exists user_fact_items_user_id_category_key_key;

create unique index if not exists idx_user_fact_items_active_unique
  on public.user_fact_items (user_id, category, key)
  where superseded_by is null;

-- ─── upsert_fact_item(): memory_kind/valid_from + state-supersede branch ──────
--
-- Returns jsonb (not a fixed RETURNS TABLE), so a plain CREATE OR REPLACE
-- with new trailing default parameters is sufficient — same reasoning
-- documented in 202607120034_episode_consolidation.sql.
--
-- New branching: when p_memory_kind = 'state' and an active row already
-- exists for this (category, key) with a *different* value, the old row is
-- superseded (not overwritten) — a new row is inserted and the old row's
-- superseded_by is pointed at it. Every other case (no existing row; an
-- existing row with an identical value; any non-'state' memory_kind,
-- including trait/event/null) behaves exactly as before this migration:
-- a plain update-in-place. This keeps event/trait/legacy-NULL rows on the
-- pre-existing single-row-per-key upsert semantics untouched (requirement:
-- no effect on trait's existing B14 behavior).
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
  p_source_experience_ids uuid[] default null,
  p_memory_kind text default null,
  p_valid_from timestamptz default null
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
  v_superseded_id uuid := null;
begin
  select id, value
  into   v_existing_id, v_old_value
  from   public.user_fact_items
  where  user_id  = v_user_id
    and  category = p_category
    and  key      = p_key
    and  superseded_by is null;

  if v_existing_id is not null and p_memory_kind = 'state' and v_old_value is distinct from p_value then
    -- Contradicting state fact: invalidate, never delete.
    insert into public.user_fact_items
      (user_id, category, key, value, confidence, source, notes, expires_at,
       thread_id, invocation_id, source_experience_ids, memory_kind, valid_from)
    values
      (v_user_id, p_category, p_key, p_value, p_confidence, p_source, p_notes, p_expires_at,
       p_thread_id, p_invocation_id, p_source_experience_ids, p_memory_kind,
       coalesce(p_valid_from, timezone('utc', now())))
    returning id into v_item_id;

    update public.user_fact_items
    set    superseded_by = v_item_id
    where  id = v_existing_id;

    v_superseded_id := v_existing_id;

  elsif v_existing_id is not null then
    v_item_id := v_existing_id;
    update public.user_fact_items
    set    value       = p_value,
           confidence  = p_confidence,
           source      = p_source,
           notes       = coalesce(p_notes, notes),
           expires_at  = p_expires_at,
           is_stale    = false,
           memory_kind = coalesce(p_memory_kind, memory_kind),
           valid_from  = coalesce(p_valid_from, valid_from),
           updated_at  = timezone('utc', now())
    where  id = v_item_id;
  else
    insert into public.user_fact_items
      (user_id, category, key, value, confidence, source, notes, expires_at,
       thread_id, invocation_id, source_experience_ids, memory_kind, valid_from)
    values
      (v_user_id, p_category, p_key, p_value, p_confidence, p_source, p_notes, p_expires_at,
       p_thread_id, p_invocation_id, p_source_experience_ids, p_memory_kind,
       coalesce(p_valid_from, timezone('utc', now())))
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
    'is_new',   v_existing_id is null and v_superseded_id is null,
    'superseded_id', v_superseded_id
  );
end;
$$;

-- ─── Search RPCs: exclude superseded rows, expose memory_kind ─────────────────
--
-- Both RPCs already filter is_deleted/is_stale in their WHERE clause
-- (202607150037_time_aware_search.sql). Leaving superseded_by unfiltered
-- here would let semantic/trigram search keep surfacing an invalidated
-- state fact after a newer one replaced it — directly undermining this
-- migration's whole purpose.
--
-- Also adding memory_kind as an output column (hence DROP+CREATE, the
-- established pattern for these two RPCs whenever RETURNS TABLE gains a
-- column — this is the fifth time, per 202607150037's own count of prior
-- occurrences). Without this, memory_search.py's freshness-ranking
-- (compute_freshness_multiplier(), Phase B8) would have no way to know a
-- search-result row is an 'event' and would keep using the plain
-- category-based decay curve for it at *ranking* time even though the
-- *batch* job (memory_validator.validate_all_facts()) now decays it faster
-- — the exact "ranking and the batch job must never disagree about what
-- old means" invariant that B8's own code comment documents. Exposing
-- memory_kind here keeps that invariant true instead of silently breaking
-- it.

drop function if exists public.search_fact_memory(vector(768), uuid, float, int);

create function public.search_fact_memory(
  query_embedding vector(768),
  user_id_param uuid,
  match_threshold float default 0.7,
  match_count int default 5
)
returns table (
  id uuid,
  category text,
  fact_key text,
  value text,
  confidence float,
  importance_score float,
  adoption_count int,
  updated_at timestamptz,
  memory_kind text,
  similarity float
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    user_fact_items.id,
    user_fact_items.category,
    user_fact_items.key as fact_key,
    user_fact_items.value,
    user_fact_items.confidence,
    user_fact_items.importance_score,
    user_fact_items.adoption_count,
    user_fact_items.updated_at,
    user_fact_items.memory_kind,
    1 - (user_fact_items.embedding <=> query_embedding) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and user_fact_items.superseded_by is null
    and user_fact_items.embedding is not null
    and 1 - (user_fact_items.embedding <=> query_embedding) > match_threshold
  order by user_fact_items.embedding <=> query_embedding
  limit match_count;
$$;

drop function if exists public.search_fact_memory_trgm(text, uuid, float, int);

create function public.search_fact_memory_trgm(
  query_text text,
  user_id_param uuid,
  match_threshold float default 0.15,
  match_count int default 5
)
returns table (
  id uuid,
  category text,
  fact_key text,
  value text,
  confidence float,
  importance_score float,
  adoption_count int,
  updated_at timestamptz,
  memory_kind text,
  similarity float
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    user_fact_items.id,
    user_fact_items.category,
    user_fact_items.key as fact_key,
    user_fact_items.value,
    user_fact_items.confidence,
    user_fact_items.importance_score,
    user_fact_items.adoption_count,
    user_fact_items.updated_at,
    user_fact_items.memory_kind,
    similarity(user_fact_items.search_text, query_text) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and user_fact_items.superseded_by is null
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
$$;
