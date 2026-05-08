create table if not exists public.push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  user_agent text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.travel_notification_deliveries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  event_id uuid not null references public.events(id) on delete cascade,
  notification_kind text not null default 'departure_reminder',
  scheduled_for timestamptz not null,
  delivered_at timestamptz not null default timezone('utc', now()),
  created_at timestamptz not null default timezone('utc', now()),
  unique (user_id, event_id, notification_kind, scheduled_for)
);

create index if not exists idx_push_subscriptions_user_id
on public.push_subscriptions (user_id);

create index if not exists idx_travel_notification_deliveries_user_event
on public.travel_notification_deliveries (user_id, event_id);

drop trigger if exists set_push_subscriptions_updated_at on public.push_subscriptions;
create trigger set_push_subscriptions_updated_at
  before update on public.push_subscriptions
  for each row execute procedure public.set_updated_at();

alter table public.push_subscriptions enable row level security;
alter table public.travel_notification_deliveries enable row level security;

create policy "push_subscriptions_all_own"
on public.push_subscriptions
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "travel_notification_deliveries_select_own"
on public.travel_notification_deliveries
for select
using (auth.uid() = user_id);
