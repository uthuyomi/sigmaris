-- Audit log for event writes: tracks what changed, who changed it, and why.

create table if not exists public.event_audit_logs (
  id uuid primary key default gen_random_uuid(),
  event_id uuid references public.events(id) on delete set null,
  user_id uuid not null references auth.users(id) on delete cascade,
  action text not null check (action in ('created', 'updated', 'deleted', 'synced', 'travel_plan_saved')),
  actor_type text not null check (actor_type in ('chat', 'import', 'sync', 'agent', 'cron', 'api_direct')),
  actor_ref text,
  field_changes jsonb,
  reason text,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_event_audit_logs_event_id
  on public.event_audit_logs (event_id);

create index if not exists idx_event_audit_logs_user_created_at
  on public.event_audit_logs (user_id, created_at desc);

alter table public.event_audit_logs enable row level security;

create policy "event_audit_logs_select_own"
  on public.event_audit_logs
  for select
  using (auth.uid() = user_id);

create policy "event_audit_logs_insert_own"
  on public.event_audit_logs
  for insert
  with check (auth.uid() = user_id);


-- Atomically inserts one event and one audit log row in the same transaction.
create or replace function public.create_event_with_audit(
  p_event jsonb,
  p_audit jsonb
) returns jsonb
language plpgsql
as $$
declare
  v_event jsonb;
begin
  insert into public.events (
    user_id, title, description, location_text,
    starts_at, ends_at, source_type, external_event_id,
    calendar_connection_id, metadata
  )
  values (
    (p_event->>'user_id')::uuid,
    p_event->>'title',
    p_event->>'description',
    p_event->>'location_text',
    (p_event->>'starts_at')::timestamptz,
    (p_event->>'ends_at')::timestamptz,
    coalesce(p_event->>'source_type', 'manual'),
    p_event->>'external_event_id',
    nullif(p_event->>'calendar_connection_id', '')::uuid,
    coalesce(p_event->'metadata', '{}'::jsonb)
  )
  returning to_jsonb(events.*) into v_event;

  insert into public.event_audit_logs (
    event_id, user_id, action, actor_type, actor_ref, field_changes, reason
  )
  values (
    (v_event->>'id')::uuid,
    auth.uid(),
    coalesce(p_audit->>'action', 'created'),
    coalesce(p_audit->>'actor_type', 'api_direct'),
    p_audit->>'actor_ref',
    jsonb_build_object('after', v_event),
    p_audit->>'reason'
  );

  return v_event;
end;
$$;


-- Atomically inserts multiple events and one audit log row per event.
-- p_events is a JSONB array of event objects; p_audit supplies actor metadata.
create or replace function public.create_events_with_audit(
  p_events jsonb,
  p_audit jsonb
) returns jsonb
language plpgsql
as $$
declare
  v_item  jsonb;
  v_event jsonb;
  v_results jsonb := '[]'::jsonb;
begin
  if jsonb_array_length(p_events) = 0 then
    return '[]'::jsonb;
  end if;

  for v_item in select * from jsonb_array_elements(p_events)
  loop
    insert into public.events (
      user_id, title, description, location_text,
      starts_at, ends_at, source_type, external_event_id,
      calendar_connection_id, metadata
    )
    values (
      (v_item->>'user_id')::uuid,
      v_item->>'title',
      v_item->>'description',
      v_item->>'location_text',
      (v_item->>'starts_at')::timestamptz,
      (v_item->>'ends_at')::timestamptz,
      coalesce(v_item->>'source_type', 'manual'),
      v_item->>'external_event_id',
      nullif(v_item->>'calendar_connection_id', '')::uuid,
      coalesce(v_item->'metadata', '{}'::jsonb)
    )
    returning to_jsonb(events.*) into v_event;

    insert into public.event_audit_logs (
      event_id, user_id, action, actor_type, actor_ref, field_changes, reason
    )
    values (
      (v_event->>'id')::uuid,
      auth.uid(),
      coalesce(p_audit->>'action', 'created'),
      coalesce(p_audit->>'actor_type', 'api_direct'),
      p_audit->>'actor_ref',
      jsonb_build_object('after', v_event),
      p_audit->>'reason'
    );

    v_results := v_results || jsonb_build_array(v_event);
  end loop;

  return v_results;
end;
$$;


-- Atomically updates the external_event_id / metadata / calendar_connection_id
-- of one event and writes a field-level before/after audit log row.
create or replace function public.update_event_external_link_with_audit(
  p_event_id uuid,
  p_payload  jsonb,
  p_audit    jsonb
) returns jsonb
language plpgsql
as $$
declare
  v_old jsonb;
  v_new jsonb;
begin
  select to_jsonb(events.*) into v_old
  from public.events
  where id = p_event_id;

  update public.events
  set
    external_event_id    = coalesce(p_payload->>'external_event_id', external_event_id),
    metadata             = case when p_payload ? 'metadata'
                             then p_payload->'metadata'
                             else metadata end,
    calendar_connection_id = case when p_payload ? 'calendar_connection_id'
                               then nullif(p_payload->>'calendar_connection_id', '')::uuid
                               else calendar_connection_id end,
    updated_at           = timezone('utc', now())
  where id = p_event_id
  returning to_jsonb(events.*) into v_new;

  if v_new is not null then
    insert into public.event_audit_logs (
      event_id, user_id, action, actor_type, actor_ref, field_changes, reason
    )
    values (
      p_event_id,
      auth.uid(),
      coalesce(p_audit->>'action', 'synced'),
      coalesce(p_audit->>'actor_type', 'api_direct'),
      p_audit->>'actor_ref',
      jsonb_build_object(
        'before', jsonb_build_object(
          'external_event_id', v_old->'external_event_id',
          'metadata',          v_old->'metadata',
          'calendar_connection_id', v_old->'calendar_connection_id'
        ),
        'after', jsonb_build_object(
          'external_event_id', v_new->'external_event_id',
          'metadata',          v_new->'metadata',
          'calendar_connection_id', v_new->'calendar_connection_id'
        )
      ),
      p_audit->>'reason'
    );
  end if;

  return v_new;
end;
$$;
