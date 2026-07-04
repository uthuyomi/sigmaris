-- Phase B8: time-aware re-ranking.
--
-- memory_search.py's ranking pipeline needs each row's updated_at to
-- compute freshness (see memory_validator.compute_freshness_multiplier(),
-- which extends the existing category decay framework rather than
-- defining a second one). Neither search RPC has ever returned updated_at
-- before this. updated_at is used rather than created_at because Phase 1
-- (memory_validator.py's confidence decay) and Phase B3 (confirmation
-- reflection, which explicitly refreshes updated_at without necessarily
-- changing the value) both already treat updated_at as "when this fact
-- was last confirmed/touched" — using anything else here would disagree
-- with the very decay framework this feature reuses.
--
-- Same DROP+CREATE requirement as prior additions to these two RPCs'
-- RETURNS TABLE (Postgres won't let CREATE OR REPLACE add an output
-- column) -- the fourth time these two RPCs have needed a column added
-- (202606290023 -> 202607070029 -> 202607090031 -> 202607110033 -> this
-- one).

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
    1 - (user_fact_items.embedding <=> query_embedding) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
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
    similarity(user_fact_items.search_text, query_text) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
$$;
