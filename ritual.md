# The compaction-boundary ritual

One definition, two consumers. `commands/smartcompact.md` reads this file and runs all nine steps,
asking the human at step 5. `hooks/materialise.py` reads this same file and hands it to a sub-agent
with step 5 suppressed, because a hook cannot ask anyone anything. Neither consumer restates the
steps in its own words; both point here.

Source: the wiki's `architecture/The-boundary-ritual.md`, which is the authority if this file and
that page ever disagree.

Warn only. Nothing in this ritual, or in anything that runs it, ever blocks a compaction.

## The nine steps

| # | Step | Needs the human |
|---|---|---|
| 1 | Measure. Compute this session's occupancy, the compaction trigger point, and the zone (green, orange, red) from the transcript and the configured thresholds. Report the numbers | no |
| 2 | Enumerate. List every open thread: read `map.md` for threads already tracked, then read the transcript and add any thread `map.md` does not already name. A live thread is never dropped by omission | no |
| 3 | Characterise. For every enumerated thread, work out its objective, phase, last event, attention share, and idle turns. Attention share is derived from the transcript itself, never hand-maintained | no |
| 4 | Propose. Present the thread table, one proposed disposition per row, drawn from the five below | no |
| 5 | Decide | yes, once per thread |
| 6 | Write. One handoff per live thread, following the schema below | no |
| 7 | Route. Per the decided disposition: only `park` and `close` actually move a thread; `continue`, `fork` and `escalate` leave it live with its handoff written | no |
| 8 | Remap. Rewrite `map.md` whole: every thread this run touched, plus whatever was already live and untouched | no |
| 9 | Report what was written, and that it is now safe to compact | no |

## The five dispositions

| Disposition | Means | Writes | Status |
|---|---|---|---|
| `continue` | Live, resumes next session | a handoff, stays live in `map.md` | proposed, not decided |
| `park` | Suspended, may return | `parked/<thread>.md`, leaves the live list | **decided** |
| `close` | Finished or abandoned | one line appended to `closed.md` | **decided** |
| `fork` | Continues in its own session | a handoff plus a ready-to-paste `claude --resume <id> --fork-session` line. Spawns nothing | proposed, not decided |
| `escalate` | Not this session's business | one line appended to `inbox.md` | proposed, not decided |

Three of the five are proposed and not decided, so nothing routes on them yet: a thread whose
proposal is `continue`, `fork` or `escalate` is written as a handoff and left live, and only `park`
and `close` may actually route. The enum itself, all five names, is closed and is Pi's; only the
routing behaviour of three of them is still open.

## The handoff

One file per live thread: `hnd.<thread>--<datetime>.md`. Never edited after writing; a later
boundary writes a new dated file, it does not touch the old one.

| Field | Belongs | Does not belong |
|---|---|---|
| Objective | What the thread is trying to accomplish, in one sentence | The full history of how it got there |
| Phase | Where the thread sits in its own lifecycle | A restatement of the objective |
| State | The concrete facts the next session needs to resume without re-deriving them | Speculation about what should happen next |
| Next step | The single next action | A list of every possible future action |
| Pointers | File paths, commit references, links the next session needs to open | Copied content from those files |

**Disposition** is a sixth field, added by this document rather than the wiki's own schema, because
a handoff has to say which of the five it is proposing and whether that proposal has been decided.
Every handoff carries it as `<disposition> (decided)` or `<disposition> (proposed, undecided)`. In
the by-hand consumer, a disposition is `(decided)` once step 5 has confirmed it for that thread. In
the hook consumer, step 5 never runs, so every disposition on every handoff is `(proposed,
undecided)`, regardless of which of the five it names.

## Two consumers

### By hand: `commands/smartcompact.md`

Runs all nine steps, including step 5. Asks one decision per thread, in conversation. Step 7 then
routes on what was actually decided: `park` and `close` execute their write and leave the live list;
`continue`, `fork` and `escalate` are written as handoffs and stay live, per the dispositions table
above, because those three are not yet decided at the specification level even when a human has just
picked one for a given thread. The command itself has no way to trigger compaction, so it stops
after step 9 and hands the user the line to paste.

### Unattended: `hooks/materialise.py`

Step 5 needs the human and a hook cannot ask. So the hook runs steps 1 to 4 and 6 to 9, and every
enumerated thread gets a handoff carrying a *proposed* disposition explicitly marked undecided.
Nothing is parked, closed or escalated on the sub-agent's judgement, no matter what step 4 proposed
for it: step 7 is a no-op in this consumer, because nothing was ever decided for it to act on.
`hooks/inject.py` already raises undecided threads after compaction; that is where the asking
happens, in the next session, from a human.

The sub-agent this hook spawns must not write any file itself. It performs steps 1 to 4 by reading
the transcript path and the existing `map.md` it is handed, then returns exactly one fenced ` ```json
` block as its entire final answer, holding every thread it enumerated:

```json
{
  "threads": [
    {
      "thread": "short-slug",
      "disposition": "continue",
      "objective": "one sentence",
      "phase": "where this thread sits in its own lifecycle",
      "state": "the concrete facts the next session needs",
      "next_step": "the single next action",
      "pointers": ["path/or/reference", "another/one"]
    }
  ]
}
```

`disposition` is one of the five names above; it is a proposal, step 4, not a decision. An empty
`"threads": []` is a legitimate answer when the session opened no thread worth tracking. Everything
mechanical, being: filename, disposition-status suffix, table rendering, and the atomic write, is
`materialise.py`'s own job, done in Python, so the sub-agent's only job is the part that needs
judgement: reading the transcript and characterising what it finds.
