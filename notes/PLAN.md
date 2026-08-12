# Build plan

What and how. The wiki says why, and nothing here restates it. `notes/` is on
the manifest's `exclude` list, so this never ships.

Written 2026-08-12, against Foundry `0.1.2`.

## State

| Thing | Where it is |
|---|---|
| Manifest | `id: smartcompact`, `foundry: 0.1.2`, `targets: [claude-code]`. Builds green |
| Content | None. No skill, no hooks, no scripts |
| Wiki | Written and verified. The authority for every decision below |

## Blocked on a ruling

**The occupancy thresholds can fire out of order, and that is a defect, not a
preference.** The soft and hard thresholds are fractions of the effective
window; the ceiling is a fraction of the model window. On any model whose window
is at or below the configured `autoCompactWindow`, the ceiling arrives first and
the gate releases before the ritual is ever driven. On a 200,000-token model
with `autoCompactWindow` at 250,000: soft 120,000, ceiling 130,000, hard 160,000.

Nothing in step three or beyond is correct until this is settled. The wiki's
loops page states the three repairs. The recommendation there is to derive soft
and hard downward from the ceiling, because the ceiling is the only number with
a measurement behind it.

Three further gaps are open and none of them blocks: what the parent's map
records after a fork, whether anything ever reads the escalation inbox, and
whether a thread continuing forever should be noticed.

## Build order

Each step ends green before the next begins.

### 1. Repo shape

Done when the committed tree is the plugin rather than a copy of Foundry's
compiler, and a clean clone of that commit builds.

### 2. Prove a plugin-shipped hook fires at all

An inert `hooks/probe.py` that reads its stdin, appends one line to a log, and
exits 0 with no output. Four rules: `session-start`, `turn-end`,
`before-compact`, `session-end`. No `only:` key, because with one target every
writable spelling is either a no-op or a refusal.

Done when a throwaway session installed with `--plugin-dir` writes a line per
event. That is the first thing here that has never been observed, and everything
downstream assumes it.

The same run settles the hook timeout, which the spike recorded as a 1.5 second
shared budget and the current documentation puts at 600 seconds. Neither has
been re-measured and they cannot both be right.

### 3. Measurement

`hooks/state.py` resolves the state directory and is the only thing that knows
the path. `hooks/occupancy.py` reads one assistant message's usage fields and
returns a state. `smartcompact.yaml` carries the thresholds, read on every
invocation.

Done when the reported number matches a hand count against a real transcript,
and a missing or empty transcript reports zero rather than raising.

### 4. The ritual, by hand

`skills/smartcompact/SKILL.md`, written as instructions. No hook fires it.

Done when it has run clean on live work three times, and after each run the map
and one handoff per live thread read correctly cold, to someone who was not in
the session.

Those three runs are also the only chance to measure what an authored handoff
actually costs against the live context, which is still a guess.

### 5. Hooks

Only after step four has run clean three times. The advisory at the soft state,
the block at the hard state, the gate at the compaction boundary, and the final
map write at session end.

The block must clear itself or it blocks every turn forever. The gate must stop
blocking above the ceiling or it ends the session.

## Not in this version

The vault write path, scholar submission, orchestration-layer invocation on
worker sessions, per-role threshold profiles, and any harness but Claude Code.

The capture queue is not part of this product and never was. It is a separate
session helper toolkit, tracked outside this repo.
