alter table public.event_travel_plans
add column if not exists fare_text text,
add column if not exists fare_amount numeric,
add column if not exists fare_currency text,
add column if not exists transfer_count integer,
add column if not exists walking_distance_meters integer,
add column if not exists walking_duration_minutes integer,
add column if not exists selected_candidate jsonb not null default '{}'::jsonb;
