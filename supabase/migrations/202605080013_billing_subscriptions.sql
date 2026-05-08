create table if not exists public.billing_customers (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  stripe_customer_id text not null unique,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  stripe_customer_id text not null,
  stripe_subscription_id text not null unique,
  stripe_price_id text,
  plan text not null default 'pro' check (plan in ('pro')),
  status text not null,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_subscriptions_user_status
on public.subscriptions (user_id, status);

drop trigger if exists set_billing_customers_updated_at on public.billing_customers;
create trigger set_billing_customers_updated_at
  before update on public.billing_customers
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_subscriptions_updated_at on public.subscriptions;
create trigger set_subscriptions_updated_at
  before update on public.subscriptions
  for each row execute procedure public.set_updated_at();

alter table public.billing_customers enable row level security;
alter table public.subscriptions enable row level security;

create policy "billing_customers_select_own"
on public.billing_customers
for select
using (auth.uid() = user_id);

create policy "subscriptions_select_own"
on public.subscriptions
for select
using (auth.uid() = user_id);
