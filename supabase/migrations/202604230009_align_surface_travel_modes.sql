alter table public.profiles
add column if not exists preferred_travel_mode text not null default 'car';

update public.profiles
set preferred_travel_mode = 'car'
where preferred_travel_mode is null
   or preferred_travel_mode in ('train', 'bus', 'transit', 'driving');

update public.profiles
set preferred_travel_mode = 'walk'
where preferred_travel_mode = 'walking';

alter table public.profiles
alter column preferred_travel_mode set default 'car';

alter table public.profiles
drop constraint if exists profiles_preferred_travel_mode_check;

alter table public.profiles
add constraint profiles_preferred_travel_mode_check
check (preferred_travel_mode in ('bicycle', 'car', 'walk'));

alter table public.event_travel_plans
add column if not exists fare_text text,
add column if not exists fare_amount numeric,
add column if not exists fare_currency text,
add column if not exists transfer_count integer,
add column if not exists walking_distance_meters integer,
add column if not exists walking_duration_minutes integer,
add column if not exists selected_candidate jsonb not null default '{}'::jsonb;

update public.event_travel_plans
set travel_mode = 'car'
where travel_mode in ('train', 'bus', 'transit', 'driving');

update public.event_travel_plans
set travel_mode = 'walk'
where travel_mode in ('walking');

alter table public.event_travel_plans
drop constraint if exists event_travel_plans_travel_mode_check;

alter table public.event_travel_plans
add constraint event_travel_plans_travel_mode_check
check (travel_mode in ('bicycle', 'car', 'walk'));
