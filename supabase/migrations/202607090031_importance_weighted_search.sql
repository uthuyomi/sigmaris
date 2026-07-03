-- Phase B17: Memory Importance Learning — extend the existing
-- user_fact_items.importance_score (set by set_fact_category_defaults()
-- since 202606270019_trend_memory.sql) into search ranking, alongside its
-- pre-existing use in build_facts_context() (top-N sort) and
-- memory_validator.py's logical-deletion threshold (importance × confidence).
--
-- Both hybrid-search RPCs (202606290023_pgvector_memory.sql,
-- 202607070029_hybrid_search_trgm.sql) currently don't return
-- importance_score at all, so memory_search.py has no way to weight
-- results by it. Postgres doesn't allow CREATE OR REPLACE to add an output
-- column to a RETURNS TABLE — the functions must be dropped and recreated.
--
-- Backward-compat note: memory_search.py's importance-weighting defaults
-- to 0.5 (a no-op relative multiplier) whenever a row lacks
-- "importance_score" entirely, so it behaves identically whether this
-- migration has been applied yet or not — see phase_b17_report.md
-- section 1 for why that mattered here (lesson carried over from Phase A4).

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
    similarity(user_fact_items.search_text, query_text) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
$$;
