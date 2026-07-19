-- Sigmaris Live「詳細表示、+機密情報のマスキング」タスク。
--
-- 記憶検索(memory_search_finished)・ツール呼び出し(tool_call_finished)の
-- 「詳細」情報(要約より踏み込んだ、マスキング済みの部分的な内容)を、
-- ログ行クリック時に取得できるよう、一時的に保持するテーブル。
--
-- 【なぜこのテーブルが必要か】
-- 既存のagent_invocation_audit_logs(request_summary/response_summary)は
-- 既に要約データのみで、記憶の内容・ツール引数の値を一切保持していない。
-- 詳細表示機能を実現するには、イベント発行時点で計算済みの、マスキング
-- 済みの詳細を、後から(ログ行クリック時に)取得できる形で、どこかに
-- 一時的に持つ必要がある——これが本テーブルの唯一の役割である。
--
-- 【なぜagent_invocation_audit_logsへ追加せず、新規テーブルにしたか】
-- audit_logsは「1呼び出し(1ターン)につき1行」の構造だが、tool_callは
-- 1ターンに0〜複数回発生しうる(Live-4、process-steps.tsのモデル参照)。
-- 既存テーブルへdetail列を追加すると、複数回のツール呼び出しのうち
-- 1回分しか保持できない。detail_key(invocation_idまたはtool_call_id)
-- 単位で複数行を持てる、独立したテーブルにした。
--
-- 【retention(保持期間)についての申し送り】
-- masked_detailは、既にマスキング済みとはいえ、ユーザーの記憶・予定に
-- 由来する内容を含む。本タスクでは自動削除の仕組み(cronによる
-- パージ等)までは実装していない——運用者が、必要に応じて保持期間の
-- ポリシーを判断し、削除の仕組みを追加することを推奨する
-- (報告書の申し送り事項に明記)。

create table if not exists public.sigmaris_live_event_details (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  event_type     text not null check (
    event_type in ('memory_search_finished', 'tool_call_finished')
  ),
  detail_key     text not null,
  masked_detail  jsonb not null,
  created_at     timestamptz not null default timezone('utc', now())
);

create index if not exists idx_sigmaris_live_event_details_lookup
  on public.sigmaris_live_event_details (user_id, event_type, detail_key, created_at desc);

alter table public.sigmaris_live_event_details enable row level security;

create policy "sigmaris_live_event_details_select_own"
  on public.sigmaris_live_event_details
  for select
  using (auth.uid() = user_id);

create policy "sigmaris_live_event_details_insert_own"
  on public.sigmaris_live_event_details
  for insert
  with check (auth.uid() = user_id);
