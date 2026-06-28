-- Enable pgvector for fact-memory embeddings.
create extension if not exists vector;

alter table public.user_fact_items
  add column if not exists embedding vector(768);

create index if not exists user_fact_items_embedding_idx
  on public.user_fact_items
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 50);

create or replace function public.search_fact_memory(
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
