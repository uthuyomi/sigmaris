-- Phase G-4 (docs/sigmaris/phase_g_report.md): persistence for the
-- claim-level "does the response's use of this citation faithfully
-- represent what the source actually says" audit (the second of the
-- two-layer citation audit -- the first layer, "does the source URL
-- actually exist," is already structurally guaranteed by G-2 only ever
-- using citations OpenAI's web_search tool itself returned).
--
-- One row per claim per turn (a granular event log), not a periodic
-- aggregate run -- mirrors sigmaris_decision_log's shape, not sigmaris_
-- cycle_health_runs' shape. G-5 (continuous citation-precision/recall
-- measurement, not implemented by this task) is expected to aggregate
-- over these rows the same way Phase R's RC indicators aggregate over
-- sigmaris_experience/chat_messages -- this table is the raw material,
-- not the rollup.
--
-- critique_verdict records G-3's Self-Critique verdict for the same turn
-- alongside this row, so a future aggregate query can correlate "how
-- often does G-3's whole-response check disagree with G-4's per-claim
-- check" without needing a join to a G-3 table -- G-3 itself does not
-- persist anything (docs/sigmaris/phase_g_report.md Phase G-3 5章,
-- concern 5), so this is the only durable record of either check.
--
-- Same service_role_only, single-tenant pattern as sigmaris_decision_log/
-- sigmaris_experience/sigmaris_cycle_health_runs: this is Sigmaris's own
-- derived verification data, not user-owned content.

create table if not exists public.sigmaris_citation_audit_log (
  id                uuid primary key default gen_random_uuid(),
  thread_id         text,
  claim             text not null,
  source_url        text not null,
  source_title      text,
  usage             text not null check (usage in ('not_used', 'faithful', 'distorted')),
  note              text,
  critique_verdict  text check (critique_verdict in ('no_contradiction', 'minor_mismatch', 'clear_contradiction')),
  created_at        timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_citation_audit_log_created_at
  on public.sigmaris_citation_audit_log (created_at desc);

create index if not exists idx_sigmaris_citation_audit_log_usage
  on public.sigmaris_citation_audit_log (usage);

alter table public.sigmaris_citation_audit_log enable row level security;

create policy "service_role_only" on public.sigmaris_citation_audit_log
  using (auth.role() = 'service_role');
