-- Phase B14: judgment/preference pattern modeling.
--
-- Distinct from sigmaris_self_model (Sigmaris's own self-description) and
-- from user_fact_items (facts about 海星さん, not judgment axes). This
-- holds recurring patterns inferred from sigmaris_decision_log's content
-- (e.g. "コストより速度を優先する傾向がある") -- never from a single
-- decision (see backend/app/services/decision_log.py::extract_preference_patterns()
-- _MIN_SUPPORTING_DECISIONS gate), each with a traceable evidence list back
-- to the decisions it was inferred from (Phase B4 provenance philosophy).
--
-- Meta/cognitive-layer data (Sigmaris's own derived understanding of 海星さん,
-- not user-owned content the user directly CRUDs), so this follows the same
-- service_role_only RLS pattern as sigmaris_decision_log/sigmaris_self_model/
-- sigmaris_experience rather than per-user RLS.

create table if not exists public.sigmaris_user_preference_patterns (
  id                            uuid primary key default gen_random_uuid(),
  pattern_key                   text not null unique,
  pattern_statement             text not null,
  supporting_decision_ids       jsonb not null default '[]'::jsonb,
  evidence_count                integer not null default 0,
  first_detected_at             timestamptz not null default timezone('utc', now()),
  last_confirmed_at             timestamptz not null default timezone('utc', now()),
  last_analyzed_decision_count  integer not null default 0,
  created_at                    timestamptz not null default timezone('utc', now()),
  updated_at                    timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_user_preference_patterns_evidence
  on public.sigmaris_user_preference_patterns (evidence_count desc);

alter table public.sigmaris_user_preference_patterns enable row level security;

create policy "service_role_only" on public.sigmaris_user_preference_patterns
  using (auth.role() = 'service_role');

-- Reuses the shared trigger function from 202606240016_fact_memory.sql.
create trigger trg_sigmaris_user_preference_patterns_updated_at
  before update on public.sigmaris_user_preference_patterns
  for each row execute function public.set_updated_at();
