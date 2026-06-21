-- Mandatory audit trail for orchestrator-to-agent invocations.

create table if not exists public.agent_invocation_audit_logs (
  id uuid primary key default gen_random_uuid(),
  invocation_id uuid not null unique,
  user_id uuid not null references auth.users(id) on delete cascade,
  caller_agent_id text not null,
  target_agent_id text not null,
  target_endpoint text not null,
  reason text not null,
  status text not null check (
    status in ('started', 'completed', 'completed_with_fallback', 'failed')
  ),
  request_summary jsonb not null default '{}'::jsonb,
  response_summary jsonb,
  error_code text,
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  persona_version text,
  persona_hash text,
  created_at timestamptz not null default timezone('utc', now()),
  completed_at timestamptz
);

create index if not exists idx_agent_invocation_audit_user_created_at
  on public.agent_invocation_audit_logs (user_id, created_at desc);

create index if not exists idx_agent_invocation_audit_target_created_at
  on public.agent_invocation_audit_logs (target_agent_id, created_at desc);

alter table public.agent_invocation_audit_logs enable row level security;

create policy "agent_invocation_audit_select_own"
  on public.agent_invocation_audit_logs
  for select
  using (auth.uid() = user_id);

create policy "agent_invocation_audit_insert_own"
  on public.agent_invocation_audit_logs
  for insert
  with check (auth.uid() = user_id);

create policy "agent_invocation_audit_update_own"
  on public.agent_invocation_audit_logs
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
