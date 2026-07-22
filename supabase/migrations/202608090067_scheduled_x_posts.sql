-- X_POST_SELF_TIMING_SPEC: Sigmaris が投稿内容に応じて「いつ出すか」を自分で
-- 決め、その未来時刻に配信するための予約テーブル。
--
-- 従来のカテゴリX投稿は 1日4回の固定 cron を"きっかけ"に、その瞬間に生成して
-- 即投稿していた。これを「決定(内容＋時刻)→ 予約保存 → 予約時刻に配信」の
-- 2フェーズに作り替える。決定フェーズが本テーブルへ status='pending' で積み、
-- 高頻度の配信ディスパッチャが scheduled_at<=now の行を(配信直前に opsec/
-- Executive Gate を再適用の上で)実際に投稿する。
--
-- x_post_history / x_reply_log / sigmaris_cycle_health_runs 等と同じ、
-- service_role_only の単一テナントパターンを踏襲した新規テーブル。

create table if not exists public.scheduled_x_posts (
    id            uuid        primary key default gen_random_uuid(),
    text          text        not null,
    category      text        not null,
    score         double precision not null default 0,
    scheduled_at  timestamptz not null,
    status        text        not null default 'pending'
                  check (status in ('pending', 'posted', 'skipped')),
    skip_reason   text,
    tweet_id      text,
    created_at    timestamptz not null default timezone('utc', now()),
    posted_at     timestamptz
);

-- 配信ディスパッチャの主クエリ(status='pending' かつ scheduled_at<=now)用。
create index if not exists idx_scheduled_x_posts_due
    on public.scheduled_x_posts (status, scheduled_at);

-- 1日上限(pending+posted)・最小間隔チェックのための時系列参照用。
create index if not exists idx_scheduled_x_posts_scheduled_at
    on public.scheduled_x_posts (scheduled_at desc);

alter table public.scheduled_x_posts enable row level security;

create policy "service_role_only" on public.scheduled_x_posts
  using (auth.role() = 'service_role');
