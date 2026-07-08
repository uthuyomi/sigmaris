-- Phase C-full-2: SB-3 (memory_duplicate_rate) columns on the existing
-- sigmaris_eval_runs table (Phase C-mini).
--
-- Deliberately extends sigmaris_eval_runs rather than creating a new
-- table: SB-3 is computed inside the same run_eval.py execution, against
-- the same active user_fact_items snapshot, and displayed alongside
-- memory_f1_score/rag_ndcg_score/response_error_rate in the same CLI
-- output row (docs/sigmaris/phase_c_full_report.md, Phase C-full-2
-- section) — it is another *internal* metric in the C-mini sense, not a
-- public-benchmark score like sigmaris_bench_runs (Phase C-full-1), which
-- got its own table specifically because that distinction (internal PDCA
-- signal vs. externally comparable score) needed to be structurally
-- unmissable. SB-3 has no such distinction from its table-mates.

alter table public.sigmaris_eval_runs
  add column if not exists memory_duplicate_rate  float,
  add column if not exists duplicate_fact_count    integer,
  add column if not exists duplicate_cluster_count integer;
