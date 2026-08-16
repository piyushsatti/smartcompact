# What the field survey says we have to do better

Read against `notes/research/res.smart_compact--field_survey--20260815.md` and the design in the
wiki. Written 2026-08-15. Nothing here is decided: it is an assessment, and the rulings it asks
for are listed at the foot.

`notes/` is excluded from the build, so this never ships.

## Verdict

- The survey confirms the premise hard. Compaction loses the things we set out to protect, and the
  field's number is brutal: the compactors it surveyed retain **17% of session constraints** on
  average, and most perform worse than not compacting at all. That is a field number, not a
  measurement of Claude Code; this repo has not measured constraint retention the same way.
- Two of our design choices are not gaps but **criticisms**. Our trigger is capacity-based, which
  the field has moved away from. Our ritual runs inline, at the moment the model is least capable.
- Four things are missing from the handoff entirely: behavioural constraints, an artifact trail,
  provenance, and any notion of staleness.
- We have no way to tell whether any of this beats Claude Code's own compaction. That is the gap
  that makes every other gap unarguable, because without it every claim here is taste.

## 1. What we already got right, and should not lose

| What we do | What the field says |
|---|---|
| An authored handoff instead of a summary of a summary | Sourcegraph retired compaction in Amp because recursive summarisation distorts earlier reasoning as compaction events accumulate. Handoff replaced it |
| One state file, rewritten whole, not an append-only corpus | LangGraph's short-term memory is append-only and recency-truncated, so contradictory or outdated information cannot be removed. Ours can |
| The gate stops blocking above the ceiling | Nobody else documents this failure mode. It is ours and it is measured |
| A human rules on each thread | No surveyed system puts a person in the disposition loop. Every one of them either lets the model decide or captures passively |

That last row is worth holding onto. The whole field is automating the judgement call. We are not,
and that is a position, not an oversight.

## 2. The trigger is the old model

**This is the sharpest finding and it goes against our current design.**

We trigger on occupancy: soft, hard, ceiling, all fractions of a window. The survey's position is
that capacity triggering is the previous generation, for a specific reason: *the model is at its
least intelligent point exactly when it must compact*. Two independent moves away from it:

| Who | What they did |
|---|---|
| Anthropic | Session guidance is now "new task, new session", with the operative question "is this current context still helping?" |
| Sourcegraph | Retired compaction outright in favour of handoff, where the developer names a goal for the next phase and only what serves it carries forward |

The survey names intent-driven triggering as one of two places this project could genuinely
contribute, and we do not do it.

**What better looks like.** The boundary fires when the work changes, not when a counter fills.
Occupancy stops being the trigger and becomes the backstop: the thing that fires when intent
detection missed. The survey's own caution is that automatic mid-session confusion detection is
unsolved and the false-positive cost is high, so the low-risk version is detecting explicit task
transitions and offering a goal-specified handoff, not guessing.

## 3. Synthesis happens in the worst possible place

Our ritual runs **inline**: the session that is out of room does its own triage, with the model
that is already degraded, spending the context it is short of.

The survey splits the field cleanly and the evidence favours the other side:

| System | Where synthesis runs |
|---|---|
| claude-mem | Async background worker, using the user's own Claude Code auth |
| Mem0 | Passive capture, async extraction |
| Letta | Inline, agent self-edits. Named tradeoff: "memory quality depends entirely on the model's judgment. If the model fails to save something, it's gone" |

Async wins on three counts: it keeps the interactive attention budget on the task, it adds no
tokens to a context already under pressure, and **the synthesis model does not have to be the
working model**. That last one matters more than it looks. It decouples handoff quality from
whatever model the session happens to be running.

**What better looks like.** Capture runs continuously and cheaply through hooks. Synthesis runs
outside the session. The ritual stops being "stop and think hard" and becomes "here is what was
already assembled, rule on it", which is also a much shorter interruption for a person.

**The tension to resolve.** Our value is that a human rules per thread. Async synthesis does not
remove that: it moves the expensive part off the critical path and leaves the human the judgement
call, which is the part that actually needs a person.

## 4. The handoff carries the wrong four things, and misses four others

Our schema is objective, phase, state, next step, pointers. It is entirely task-shaped. Every one
of the misses below is a category the field has measured being destroyed.

### 4.1 Behavioural constraints, the 17% finding

"Lost in Compaction" defines session constraints as instructions that constrain *how* a task is
done, not what it is: "confirm with me before taking any action". The field's compactors retain 17%
of them on average; a dedicated extractor gets over 90%. That is a finding about the field, not a
measurement of Claude Code.

We have no slot for these at all. A session where Pi said "ask before every commit" has nowhere to
carry that past the boundary. This is the single clearest thing to add, and it is the difference
between preserving what the work is and preserving how it must be done. The baseline to beat is our
own, not the field's: native compaction on chronicler `868ee7ac` scored 22 of 48 on a held-out fact
set, against 32 to 37 of 48 for four candidate handoff formats on the same set; section 6 has the
full comparison.

### 4.2 The artifact trail

Factory.ai's probe evaluation scores compaction on six dimensions. Every method scored badly on
tracking which files were created, modified or examined; Factory's own best was **2.45 out of 5**.
Their conclusion: this needs dedicated state tracking, not summarisation. OpenAI's compressor
discards file paths outright as low-entropy.

Our `pointers` field is a free-text gesture at this. It is not a tracked artifact list and nothing
populates it mechanically.

### 4.3 Provenance

Mem0 tags what the user typed as the user's and what the assistant produced as the assistant's,
"so its suggestions never become your stated preferences". Ours are all assistant-written, with a
human approving a disposition, and nothing records which is which. There is also a security edge:
prompt injection into persistent agent memory is demonstrated, so provenance is a trust boundary
and not only a bookkeeping nicety.

### 4.4 Staleness

We have none. `closed.md` and `inbox.md` append forever, and nothing ever expires. Mem0's policy is
typed: session state and compaction summaries expire on a horizon, while decisions, anti-patterns
and conventions never do. Zep's Graphiti is the more careful version, marking a superseded fact
with a validity interval rather than deleting it, so history survives.

The failure this prevents is concrete: stale session data outranking a real preference at retrieval
time.

## 5. Everything is one scope

Our state is per project, keyed inside the plugin's data directory. There is no user-level or
cross-project layer. Google ADK, the cleanest separation surveyed, uses four scopes: session, user,
app, and a temp that is never persisted. Its named failure mode is "conflating history (what was
said) with state (what is true)", and its warning is direct: store an architectural decision at
session scope and the agent forgets it next run.

Whether smartcompact wants a durable cross-project layer is a product question, not an engineering
one. It is worth asking rather than defaulting.

## 6. We cannot tell whether any of this works

There is no evaluation harness. Beyond one preliminary chained comparison (below), we cannot say
whether an authored handoff beats Claude Code's own compaction.

Factory's six-dimension probe scheme is the available template: accuracy, context awareness,
artifact trail, completeness, continuity, instruction following, scored zero to five with a model
as judge. The survey notes no standardised open harness exists, and that most benchmarks test a
single compaction event rather than the recursive chains that cause real degradation.

Two field numbers sit here as reference points: **17% constraint retention**, the average across
the compactors "Lost in Compaction" surveyed, and **2.45/5 artifact tracking**, Factory's own best
score. Neither is Claude Code's number, and this repo now has one that is: native compaction on
chronicler `868ee7ac` retained 22 of 48 held-out facts one boundary past a cut and 3 of 48 six
boundaries past, while four candidate handoff formats held inside a 10,000 character budget scored
32 to 37 of 48 at five boundaries (`research/results/chain/868ee7ac-30-40/`). That is the number a
redesigned handoff actually has to clear.

This also decides the product's shape. If structured handoff wins by a wide margin, replace native
compaction. If it does not, ride native compaction and inject at the boundary, which is far less
engineering.

## 7. Adopt, do not build

The survey is blunt that most of this is commodity: lifecycle-hook capture, local storage,
provenance tagging, typed expiry, scoped state, async workers, precedence on inject. Reference
implementations exist in claude-mem, Mem0, ADK and OpenAI's cookbook.

One item needs verifying before it can be adopted: Anthropic's Developer Platform now has a
`pause_after_compaction` option that injects content blocks after the summary is generated and
before the conversation continues. If Claude Code exposes it, it is a better injection point than
anything we have, because our `before-compact` hook can only block and cannot inject. **Unverified.
It is described for the API, not for Claude Code's hooks, and the two are not the same surface.**

## 8. What this does not change

The threshold ordering defect is still the blocking one, and none of this touches it. The ceiling
can still arrive before the hard threshold and release the gate before anything is written.

The five dispositions are still ours and three still lack semantics.

## Rulings this asks for

| # | Question |
|---|---|
| 1 | Does the trigger stay capacity-based, gain intent detection, or invert so intent leads and occupancy is only the backstop |
| 2 | Does synthesis move out of the session into an async worker, and if so does the human ruling stay |
| 3 | Does the handoff grow a constraints layer, an artifact trail, provenance tags and expiry, or some subset |
| 4 | Is there a durable layer above the project, or does everything stay project-scoped |
| 5 | Does an evaluation harness get built before v1, so the product's shape is decided by measurement rather than by taste |
