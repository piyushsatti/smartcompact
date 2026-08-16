# What real sessions actually look like

Measured 2026-08-15 with a script over Claude Code's own transcripts, streaming line by line.
Occupancy is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` on one
assistant message, never summed across turns. Sidechain lines are excluded.

Script: `analyse.py` in the session scratchpad. Every number below is reproducible from the
transcripts named.

`notes/` is excluded from the build, so this never ships.

## Verdict

- One chronicler session compacted **64 times over 25 days**, and those compactions are recursive:
  each summarised content that already held the previous summaries.
- The same session spawned **630 sub-agents** and still compacted 64 times. Offloading heavy work
  is necessary and nowhere near sufficient.
- Median occupancy before a compaction was **265,889**, independently reproducing the 268,906
  measured earlier over a different sample of 106 compactions. That figure is now solid.
- **A live session is running at 455,131 with no compaction.** The effective window assumed by the
  design does not describe what is actually happening, so the thresholds are computed against the
  wrong denominator.

## The orchestrator: chronicler `868ee7ac`

`~/.claude/projects/-Users-piyushsatti-Studio-Developer-projects-chronicler-chronicler/868ee7ac-cd10-4618-83e0-c93f0e03e8c7.jsonl`

| Measure | Value |
|---|---|
| File | 152 MB, 79,019 lines, branch `main` |
| Span | 2026-07-11 to 2026-08-05, 25 days, one session id |
| User turns | 2,114 |
| Compaction events | 64 |
| Peak occupancy before each | min 78,835 · median 265,889 · max 829,374 |
| Peak overall | 829,374 |
| Sub-agent spawns | 630 |
| Sidechain lines in file | 0 |

**Corrected 2026-08-16.** User turns is 2,114, counting only text a person typed. An earlier pass
put this at 9,131 by counting every `type=="user"` record in the transcript, which also includes
tool-result carriers and injected task notifications. `research/harness/distill.py`'s `user_text()`
discards both and keeps only what a human wrote; `data/corpus/868ee7ac/meta.json` records the result
as `user_turns: 2114`.

Sub-agent breakdown: 461 `general-purpose`, 81 default, 39 `crucible:panelist`, 12 `Explore`,
8 `crucible:red-attacker`, 7 `feature-dev:code-reviewer`, 6 `crucible:blue-verifier`, 5 `architect`,
and a long tail.

Tools: 3,414 `Bash`, 796 `Edit`, 630 `Agent`, 342 `SendMessage`, 312 `Read`, 225 `Write`,
143 `Workflow`, 134 `TaskUpdate`, 110 `AskUserQuestion`, 100 `ScheduleWakeup`.

### Compaction cadence

Compacted on 24 of 25 days. Only 2026-07-26 had none.

```
07-11 #        07-19 ###      07-27 ###
07-12 ###      07-20 #        07-28 ###
07-13 ######   07-21 ###      07-29 #
07-14 ###      07-22 #        07-30 ##
07-15 #        07-23 ##       07-31 #####
07-16 #        07-24 #        08-01 #######
07-17 #        07-25 ##       08-02 ####
07-18 ##       07-26 .        08-03 ####
                              08-04 ###
                              08-05 #
```

### Three things this establishes

**The recursion is real and it is deep.** Each compaction summarises the window as it stands, which
already contains the output of every prior compaction. Sixty-four levels of that is the exact
failure mode that drove Sourcegraph to retire compaction in favour of handoff.

**Prevention by delegation is already happening and it is not enough.** 630 spawns did not save the
orchestrator, because the orchestrator's job is to hold the thread: it accumulates every returned
digest plus 2,114 turns of its own reasoning about them. Offloading tangents helps a session that
wanders. It does not help a session whose purpose is continuity.

**The min is as interesting as the median.** A compaction fired with a peak of only 78,835 ahead of
it, well under any configured trigger. Either a manual compaction, or a trigger that does not work
the way the design assumes. Not chased down.

## This session, dogfooded

`~/.claude/projects/-Users-piyushsatti-Studio-Developer-projects-smartcompact/54a3f836-afb9-4ade-a6c9-e14a739346db.jsonl`

| Measure | Value |
|---|---|
| Span | 2026-08-09 to 2026-08-15, 6 days |
| User turns | 421 |
| Compaction events | 2, at file lines 611 and 1473 |
| Peak before each | 215,455 and 216,068 |
| Occupancy since the last one | 81,965 rising to 455,131 over 411 assistant messages, no compaction |
| Sub-agent spawns | 14 |

**The anomaly.** Two compactions fired near 216,000, consistent with a 250,000 trigger. The session
then ran past 455,000 without firing again. Two candidate explanations and this document picks
neither: the window in play is far larger than the design assumes, or auto-compaction stopped
firing, which is what the unresolved `autoCompactEnabled` disagreement between
`~/.claude/settings.json` and `~/.claude.json` would look like from the outside.

Either way, **the design computes every threshold against `min(model window, autoCompactWindow)`
and that expression does not describe this session.** This needs settling before any threshold is
implemented, and it compounds the already-open ordering defect.

## What this changes

| Finding | Consequence |
|---|---|
| 64 recursive compactions in one session | The premise is not theoretical. This is the artefact the product exists to prevent, and there is a named session to measure against |
| 630 spawns, still 64 compactions | Sub-agent prevention is a component, not the answer. An orchestrator needs the boundary ritual regardless |
| Median 265,889, reproduced on a second sample | The trigger point is well characterised. Nothing else about the thresholds is |
| A live session at 455,131 uncompacted | The effective-window formula is unvalidated against real behaviour |

## What was not measured

Whether the stack shape is recoverable from a transcript. The counts above say how much traffic
there is and how often it collapses; they say nothing about whether a push, a pop or a split can be
detected after the fact. That is the research surface and it needs a different instrument.

`868ee7ac` is the obvious corpus for it: 2,114 user turns of real work with 64 known collapse points
already marked.
