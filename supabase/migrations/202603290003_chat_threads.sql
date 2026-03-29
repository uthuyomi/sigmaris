create table if not exists public.chat_threads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  title text not null default '新しいチャット',
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.chat_threads(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  message_order integer not null,
  role text not null check (role in ('system', 'user', 'assistant')),
  parts jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (thread_id, message_order)
);

create index if not exists idx_chat_threads_user_updated_at
on public.chat_threads (user_id, updated_at desc);

create index if not exists idx_chat_messages_thread_order
on public.chat_messages (thread_id, message_order asc);

drop trigger if exists set_chat_threads_updated_at on public.chat_threads;
create trigger set_chat_threads_updated_at
  before update on public.chat_threads
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_chat_messages_updated_at on public.chat_messages;
create trigger set_chat_messages_updated_at
  before update on public.chat_messages
  for each row execute procedure public.set_updated_at();

alter table public.chat_threads enable row level security;
alter table public.chat_messages enable row level security;

create policy "chat_threads_all_own"
on public.chat_threads
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "chat_messages_all_own"
on public.chat_messages
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
