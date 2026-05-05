create index if not exists idx_events_active_user_starts_at
on public.events (user_id, starts_at)
where status <> 'cancelled';

create index if not exists idx_events_active_user_starts_ends
on public.events (user_id, starts_at, ends_at)
where status <> 'cancelled';

create index if not exists idx_saved_locations_user_default_created
on public.saved_locations (user_id, is_default_departure desc, created_at asc);

create index if not exists idx_event_travel_plans_event_id
on public.event_travel_plans (event_id);
