-- research_items: AI research findings with 7-day auto-expiry.
-- x_post_history: X post history for similarity dedup and post-type rotation.
-- Both tables are service-role-only (no user RLS policies).

create table if not exists public.research_items (
    id                   uuid        primary key default gen_random_uuid(),
    source               text        not null,                        -- 'arxiv' | 'github' | 'news'
    title                text        not null,
    url                  text        not null,
    summary              text,
    relevance            text        not null check (relevance in ('HIGH', 'MEDIUM', 'LOW')),
    sigmaris_perspective text,                                         -- first-person Sigmaris comment
    posted_to_x          bool        not null default false,
    expires_at           timestamptz not null default (timezone('utc', now()) + interval '7 days'),
    created_at           timestamptz not null default timezone('utc', now())
);

create index if not exists idx_research_items_created_at
    on public.research_items (created_at desc);
create index if not exists idx_research_items_expires_at
    on public.research_items (expires_at);
create index if not exists idx_research_items_relevance
    on public.research_items (relevance, created_at desc);

alter table public.research_items enable row level security;
-- No user policies: only service_role (bypasses RLS) may read/write.


create table if not exists public.x_post_history (
    id          uuid        primary key default gen_random_uuid(),
    text        text        not null,
    post_type   text        not null,   -- 'memory_gained' | 'research_discovery' | 'self_update' | 'quiet_observation'
    posted_at   timestamptz not null default timezone('utc', now()),
    created_at  timestamptz not null default timezone('utc', now())
);

create index if not exists idx_x_post_history_posted_at
    on public.x_post_history (posted_at desc);
create index if not exists idx_x_post_history_post_type
    on public.x_post_history (post_type, posted_at desc);

alter table public.x_post_history enable row level security;
-- No user policies: only service_role may read/write.
