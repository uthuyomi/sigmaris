-- Phase A4: optimistic concurrency control for chat_threads/chat_messages.
--
-- replace_chat_messages() does a full delete-then-reinsert of a thread's
-- messages with no conflict detection: two concurrent writers to the same
-- thread_id could silently clobber each other, with whichever finishes last
-- winning outright. `version` acts as a compare-and-swap token: every
-- successful replace_chat_messages() call increments it, gated on the
-- caller's expected_version still matching. A mismatch means someone else
-- wrote first, and the request is rejected before chat_messages is touched.

alter table public.chat_threads
  add column if not exists version integer not null default 1;
