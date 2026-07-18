-- Phase H-3 (docs/sigmaris/phase_h_report.md): 承認フロー、及び、実際の投稿
--
-- H-2.5で追加した`reply_draft_status`(not_generated/pending_post/
-- generation_failed)は「返信案の生成状態」を表す列のまま変更しない。
-- 本タスクは、F-3(sigmaris_code_diff_proposals)のreview_status/
-- pr_creation_statusという「人間の決定」と「実行結果」を分離する既存
-- パターンを、そのまま踏襲し、新たに2系統の列を追加する。
--
-- review_status: 海星さんによる、承認・却下の決定そのもの。
--   'pending'   -- まだ決定していない(既定値。reply_draft_status=
--                  'pending_post'になった時点で、この列も'pending'の
--                  まま——生成された全ての返信案が、無条件に、この
--                  レビュー待ちキューに入る)
--   'approved'  -- 海星さんが、明示的に承認した
--   'rejected'  -- 海星さんが、明示的に却下した
--
-- post_status: 承認後、実際にXへ投稿を試みた結果(review_status='approved'
-- になって初めて意味を持つ)。
--   'posted'               -- 実際にXへ投稿できた(posted_tweet_idに実IDが入る)
--   'failed_to_post'       -- 投稿を試みたが、x_publisher.post_tweet()が
--                             失敗した(ネットワークエラー等)
--   'blocked_by_recheck'   -- 承認は記録されたが、投稿直前の再チェック
--                             (プライバシー・品質監査の再照合)で中断した
--                             ——承認の記録自体は取り消さない(正直な監査
--                             証跡として残す、F-3のgate B原則を踏襲)

alter table public.x_reply_log
  add column if not exists review_status text
    not null default 'pending'
    check (review_status in ('pending', 'approved', 'rejected'));

alter table public.x_reply_log
  add column if not exists review_notes text;

alter table public.x_reply_log
  add column if not exists reviewed_by text;

alter table public.x_reply_log
  add column if not exists reviewed_at timestamptz;

alter table public.x_reply_log
  add column if not exists post_status text
    check (post_status in ('posted', 'failed_to_post', 'blocked_by_recheck'));

alter table public.x_reply_log
  add column if not exists posted_tweet_id text;

alter table public.x_reply_log
  add column if not exists posted_at timestamptz;

create index if not exists idx_x_reply_log_review_status
  on public.x_reply_log (review_status, detected_at asc)
  where reply_draft_status = 'pending_post';
