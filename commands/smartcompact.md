---
description: Run the nine-step compaction-boundary ritual by hand, deciding every thread's disposition, then hand you the line to paste to actually compact.
---

# smartcompact

Read `${CLAUDE_PLUGIN_ROOT}/ritual.md` in full before doing anything else. It is the one definition
of this ritual; nothing below restates its steps, it only says how to run them from here, by hand.

## What to do

Run all nine steps from `ritual.md`, in order, including step 5. That is the difference between
this command and the unattended hook: you have a human in front of you, so you ask.

1. Measure, enumerate, characterise and propose (steps 1 to 4) exactly as `ritual.md` describes.
   Present the thread table with its proposed dispositions before asking anything.
2. Decide (step 5): for each thread in the table, ask the user, one at a time, to confirm or change
   its proposed disposition. Do not batch every thread into one question. Wait for each answer before
   moving to the next thread.
3. Write, route and remap (steps 6 to 8): one handoff per live thread, per `ritual.md`'s schema, with
   its disposition marked `(decided)` rather than `(proposed, undecided)`, since a human just decided
   it. Route only `park` and `close`, per the dispositions table; rewrite `map.md` whole.
4. Report (step 9): state plainly what was written, where, and that it is now safe to compact.

## What this command cannot do

A slash command runs inside this session's own model, which has no tool that triggers compaction.
This command cannot call `/compact` for you. Once step 9 is done, print exactly this line and stop:

```
/compact
```

Tell the user to paste it themselves when ready. If `$ARGUMENTS` was given, it is the user's own
instructions for the compaction, the same `custom_instructions` the unattended hook would receive;
mention that they may append it to the pasted line themselves, for example `/compact $ARGUMENTS`, but
do not paste or run it on their behalf.
