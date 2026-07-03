-- Phase B13: implicit feedback via sigmaris_decision_log.memory_refs.
--
-- adoption_count on user_fact_items counts how many *distinct* decisions
-- actually referenced a fact (decision_log.memory_refs, populated since
-- Phase A3's detect_and_record_decision()) -- a real signal of facts
-- 海星さん's own decisions actually relied on, as opposed to facts merely
-- retrieved by search and never acted on. Positive-only: a fact search
-- surfaces but that never appears in memory_refs gets no penalty at all
-- (see backend/app/services/decision_log.py::recompute_adoption_counts()
-- and phase_b13_report.md section 1 for why "not yet referenced" is
-- deliberately never treated as a negative signal).
--
-- Same DROP+CREATE requirement as 202607090031 (Postgres won't let
-- CREATE OR REPLACE add an output column to a RETURNS TABLE) -- this is
-- the third time these two RPCs have needed a column added
-- (202606290023 -> 202607070029 -> 202607090031 -> this one).

alter table public.user_fact_items
  add column if not exists adoption_count integer not null default 0;

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
    similarity(user_fact_items.search_text, query_text) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
$$;
