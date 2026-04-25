alter table public.profiles
add column if not exists preferred_travel_mode text not null default 'train';

alter table public.profiles
drop constraint if exists profiles_preferred_travel_mode_check;

alter table public.profiles
add constraint profiles_preferred_travel_mode_check
check (preferred_travel_mode in ('train', 'bus', 'bicycle', 'car', 'walk'));

alter table public.event_travel_plans
drop constraint if exists event_travel_plans_travel_mode_check;

alter table public.event_travel_plans
add constraint event_travel_plans_travel_mode_check
check (travel_mode in ('train', 'bus', 'bicycle', 'car', 'walk'));
