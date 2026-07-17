-- Phase H-2 (docs/sigmaris/phase_h_report.md): 返信の検知、及び、
-- フィルタリング(X投稿連携、第二段階)。
--
-- 1. x_post_history.tweet_id: 実際に投稿できたX側のtweet_id。返信検知が
--    「この返信は、シグマリスのどの投稿への返信か」を突き合わせるために
--    必要(x_post_generator.py::record_post()/get_recent_tracked_posts()
--    が読み書きする)。既存の行(H-1・切り替えタスクまでに記録された分)
--    はtweet_id列が無かったためNULLのままになる——過去の投稿は、返信
--    検知の対象にはならない(新規のNULL許容列の追加のみ、既存データへの
--    影響なし)。
--
-- 2. x_reply_log: 検知した返信1件ごとに1行。x_post_history(sigmaris_
--    cycle_health_runs等)と同じ、service_role_onlyの単一テナント
--    パターンを踏襲した新規テーブル。
--    filter_outcome:
--      'developer_bypass' -- 発信元が@Oyasu1999(開発者本人)のため、
--                             フィルタリング(①②③)を適用せず、通常の
--                             会話として扱ってよいと判定した
--      'eligible'         -- 開発者以外からの返信で、①対話意図あり・
--                             ②インジェクション試行なし・③危険/迷惑
--                             内容なし、の全てを満たした
--      'ignored'          -- ①②③のいずれかに該当し、無視すると判定した
--    (実際の返信文の生成・投稿は、次のタスクの範囲——本テーブルは、
--    検知とフィルタリングの結果を記録するのみ)。

alter table public.x_post_history
  add column if not exists tweet_id text;

create index if not exists idx_x_post_history_tweet_id
  on public.x_post_history (tweet_id)
  where tweet_id is not null;

create table if not exists public.x_reply_log (
    id                    uuid        primary key default gen_random_uuid(),
    reply_tweet_id        text        not null unique,
    in_reply_to_tweet_id  text        not null,
    author_id             text,
    author_username       text,
    reply_text            text        not null,
    filter_outcome        text        not null check (filter_outcome in ('developer_bypass', 'eligible', 'ignored')),
    filter_reasons        jsonb       not null default '[]'::jsonb,
    detected_at           timestamptz not null default timezone('utc', now()),
    created_at            timestamptz not null default timezone('utc', now())
);

create index if not exists idx_x_reply_log_detected_at
    on public.x_reply_log (detected_at desc);
create index if not exists idx_x_reply_log_in_reply_to_tweet_id
    on public.x_reply_log (in_reply_to_tweet_id);
create index if not exists idx_x_reply_log_filter_outcome
    on public.x_reply_log (filter_outcome, detected_at desc);

alter table public.x_reply_log enable row level security;

create policy "service_role_only" on public.x_reply_log
  using (auth.role() = 'service_role');
