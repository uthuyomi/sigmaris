-- Phase B9: knowledge graph layer (final Phase B feature).
--
-- Deliberately the minimum viable schema per the task's explicit
-- constraint against a full graph database: two plain PostgreSQL tables,
-- traversable with ordinary SQL joins, no graph query language or engine.
--
-- This is a thin, complementary layer, not a replacement for existing
-- memory tables (explicit task constraint against duplication):
--   - user_fact_items already holds permanent facts about 海星さん.
--   - sigmaris_decision_log already holds decisions with provenance (B4).
--   - sigmaris_topic_log already holds conversational topic drift (B6).
--   - sigmaris_user_preference_patterns already holds judgment tendencies (B14).
-- None of that content is duplicated here. sigmaris_entities holds only a
-- name and a type (no copied fact/decision text), and sigmaris_entity_
-- relations' source_table/source_id columns POINT BACK at whichever of
-- the tables above a relation was derived from, rather than copying its
-- content. The graph's only job is to record *that a relationship exists
-- between two named things* — the substance of what happened still lives
-- in exactly one place.
--
-- Same service_role_only, single-tenant RLS pattern as every other B-group
-- table (sigmaris_decision_log/experience/topic_log/user_preference_
-- patterns/abstention_feedback/goal_alignment_flags).

create table if not exists public.sigmaris_entities (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  entity_type text not null check (entity_type in ('person', 'place', 'project', 'technology', 'other')),
  created_at  timestamptz not null default timezone('utc', now()),
  unique (name, entity_type)
);

create table if not exists public.sigmaris_entity_relations (
  id             uuid primary key default gen_random_uuid(),
  from_entity_id uuid not null references public.sigmaris_entities(id) on delete cascade,
  to_entity_id   uuid not null references public.sigmaris_entities(id) on delete cascade,
  relation_type  text not null,
  -- Provenance: which existing table/row this relation was derived from
  -- (e.g. source_table='sigmaris_decision_log', source_id=<that row's id>)
  -- -- not a copy of that row's content, just a pointer back to it.
  source_table   text,
  source_id      uuid,
  created_at     timestamptz not null default timezone('utc', now()),
  unique (from_entity_id, to_entity_id, relation_type)
);

create index if not exists idx_sigmaris_entity_relations_from
  on public.sigmaris_entity_relations (from_entity_id);

create index if not exists idx_sigmaris_entity_relations_to
  on public.sigmaris_entity_relations (to_entity_id);

alter table public.sigmaris_entities enable row level security;
alter table public.sigmaris_entity_relations enable row level security;

create policy "service_role_only" on public.sigmaris_entities
  using (auth.role() = 'service_role');

create policy "service_role_only" on public.sigmaris_entity_relations
  using (auth.role() = 'service_role');
