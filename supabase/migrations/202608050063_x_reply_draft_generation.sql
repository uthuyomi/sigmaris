-- Phase H-2.5 (docs/sigmaris/phase_h_report.md): 返信案の生成
--
-- H-2で作った`x_reply_log`に、返信案(投稿待ち)の列を追加する。新テーブル
-- ではなく既存テーブルへの追加にした判断根拠: x_reply_logは、検知した
-- 返信1件につき1行という構造が既にあり、返信案もその返信1件に対して
-- 常に1つしか存在しない(1:1)。別テーブルにするとJOINが必要になるだけで、
-- 得られる利点がないため、既存行への追加列で表現した。
--
-- reply_draft_status:
--   'not_generated'      -- まだ返信案を生成していない(既定値。H-2までの
--                            既存行は全てこの状態のまま)
--   'pending_post'        -- 返信案の生成・全フィルタ通過が完了し、投稿待ち
--                            (本タスクでは、実際の投稿は一切行わない——
--                            次のタスクH-3が、承認フローとともに実装する)
--   'generation_failed'   -- 生成を試みたが、フィルタを通過する案を作れな
--                            かった(全リトライ失敗)
--
-- reply_draft_audience: 'developer'(@Oyasu1999向け) または 'general'
-- (それ以外の一般ユーザー向け)。生成ロジックの分岐に使った値をそのまま
-- 記録する(依頼書要件2の直接的な検証材料)。

alter table public.x_reply_log
  add column if not exists reply_draft_text text;

alter table public.x_reply_log
  add column if not exists reply_draft_audience text
    check (reply_draft_audience in ('developer', 'general'));

alter table public.x_reply_log
  add column if not exists reply_draft_status text
    not null default 'not_generated'
    check (reply_draft_status in ('not_generated', 'pending_post', 'generation_failed'));

alter table public.x_reply_log
  add column if not exists reply_draft_score numeric;

alter table public.x_reply_log
  add column if not exists reply_draft_generated_at timestamptz;

create index if not exists idx_x_reply_log_draft_status
  on public.x_reply_log (reply_draft_status, detected_at desc);
