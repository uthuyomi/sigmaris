alter table public.profiles
add column if not exists arrival_lead_minutes integer not null default 10;

alter table public.profiles
drop constraint if exists profiles_arrival_lead_minutes_check;

alter table public.profiles
add constraint profiles_arrival_lead_minutes_check
check (arrival_lead_minutes >= 0 and arrival_lead_minutes <= 180);
