alter table public.profiles
add column if not exists ai_tone text not null default 'default';

alter table public.profiles
drop constraint if exists profiles_ai_tone_check;

alter table public.profiles
add constraint profiles_ai_tone_check
check (ai_tone in ('default', 'friendly', 'concise', 'direct'));
