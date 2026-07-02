-- Phase A1: cross-thread recent-message window support.
-- get_recent_messages_across_threads() queries chat_messages by user_id
-- ordered by created_at desc, across all threads (not filtered by thread_id).
-- The existing idx_chat_messages_thread_order index is thread-scoped and does
-- not serve this access pattern.

create index if not exists idx_chat_messages_user_created_at
  on public.chat_messages (user_id, created_at desc);
