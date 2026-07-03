-- Phase B1: hybrid search — pg_trgm keyword/fuzzy matching alongside the
-- existing pgvector semantic search (search_fact_memory, from
-- 202606290023_pgvector_memory.sql).
--
-- Vector search is strong on semantic similarity but weak on exact proper
-- nouns ("ThinkPad T14", "シグマリス") — a query embedding for a short,
-- specific keyword doesn't reliably land near the embedding of a fact
-- containing that same keyword verbatim. pg_trgm's character-trigram
-- similarity catches these substring/near-exact matches directly, with no
-- dependency on embedding quality. Chosen over tsvector/to_tsquery because
-- Japanese has no whitespace word boundaries for a default text-search
-- config to split on (would need pg_bigm or a Japanese-aware config, not
-- guaranteed available); pg_trgm is a standard, always-available Postgres
-- contrib extension that works at the character level regardless of
-- language, and specifically excels at the Latin-alphanumeric proper nouns
-- (product names, etc.) this feature targets. See phase_b1_report.md
-- section 1 for the full comparison.

create extension if not exists pg_trgm;

-- Mirrors the exact field concatenation memory_search.py::_fact_embedding_text()
-- already uses to build the text that gets embedded, so both search paths
-- are matching against equivalent text.
alter table public.user_fact_items
  add column if not exists search_text text
  generated always as (
    coalesce(category, '') || ' ' || coalesce(key, '') || ' ' ||
    coalesce(value, '') || ' ' || coalesce(notes, '')
  ) stored;

create index if not exists user_fact_items_search_text_trgm_idx
  on public.user_fact_items
  using gin (search_text gin_trgm_ops);

create or replace function public.search_fact_memory_trgm(
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
    similarity(user_fact_items.search_text, query_text) as similarity
  from public.user_fact_items
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
$$;
