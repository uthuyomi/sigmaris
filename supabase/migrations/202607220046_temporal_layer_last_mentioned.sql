-- Temporal Layer Step 2: last_mentioned_at (spontaneous-mention tracking).
--
-- Problem this addresses (continuing 202607220045_temporal_memory_layer.sql,
-- 海星さん's report that Sigmaris re-reports days-old events as if they just
-- happened): Step 1 gave event facts faster decay and a memory_kind label,
-- but did nothing to stop Sigmaris from *spontaneously* re-surfacing the same
-- already-mentioned event in every morning briefing / check-in until it
-- decays out of the top-5 importance ranking. last_mentioned_at tracks the
-- last time Sigmaris *actively* (self-initiated, not in reply to a question)
-- said this event out loud, so the proactive briefing path can skip events
-- it has already told the user about, while ordinary Q&A remains completely
-- unaffected (it never reads or filters on this column — see
-- backend/app/services/orchestrator/service.py's is_proactive gate and
-- docs/sigmaris/temporal_layer_report.md).
--
-- Nullable, no CHECK restricting it to memory_kind='event' rows: enforcing
-- that at the DB layer would need a trigger for no real benefit — the
-- application code only ever reads/writes this column for event-kind
-- rows (see mark_facts_mentioned()/build_facts_context() in
-- user_fact_data.py), so a state/trait row simply never gets it set.

alter table public.user_fact_items
  add column if not exists last_mentioned_at timestamptz;
