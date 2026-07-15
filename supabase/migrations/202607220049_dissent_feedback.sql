-- Phase S-3 (docs/sigmaris/phase_s_report.md): reactions to dissent,
-- observed the same way Phase B15 observes reactions to hedged answers.
--
-- Explicitly reuses sigmaris_abstention_feedback (B15) rather than
-- creating a new table -- the task's constraint is "do not build a new
-- data-collection mechanism, use only B14/B15's existing data/mechanism".
-- B15's mechanism *is* "mark a pending event -> classify the user's next
-- reply -> aggregate into a bounded offset"; this migration widens the one
-- constraint that was scoped specifically to hedging (the `reaction`
-- CHECK) so the exact same table/mechanism can also hold dissent
-- reactions, distinguished purely by value, not by a parallel table.
--
-- Follows the same "drop the old CHECK, add a wider one" pattern already
-- established by 202607040026_decision_log_supersede.sql for
-- sigmaris_decision_log_decision_type_check.

alter table public.sigmaris_abstention_feedback
  drop constraint if exists sigmaris_abstention_feedback_reaction_check;

alter table public.sigmaris_abstention_feedback
  add constraint sigmaris_abstention_feedback_reaction_check
  check (reaction in (
    'push_for_answer', 'supports_caution',
    'dissent_accepted', 'dissent_pushed_back'
  ));
