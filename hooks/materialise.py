#!/usr/bin/env python3
"""Before-compact hook: runs the ritual unattended, and never blocks the compaction it guards.

Every compaction boundary, automatic or by hand, fires this hook first. Step 1 of the ritual,
recording occupancy and zone to boundaries.jsonl, happens unconditionally and before anything else
in this file, because a hook can be killed at any point after that and the boundary must still be on
record. Everything past that point is best-effort: spawn a sub-agent to run the ritual's judgement
steps (2 through 4), write whatever it hands back, or write a deterministic skeleton instead. This
file never decides a thread's disposition; step 5 needs a human and this is not one. See ritual.md
for what the sub-agent is actually told to do, and hooks/inject.py for where the human is asked.

Three timeouts nest inside one another on purpose: the rule in hooks.yaml allows 120 seconds, the
subprocess timeout below is 90, and the sub-agent's own instructions ask for nothing that should take
that long. Each budget sits strictly inside the one above it, so the sub-agent always dies first and
this file always has time left to write its fallback rather than being killed mid-write itself.

Reentrancy: hooks are installed globally, so a spawned `claude -p` runs these same hooks, including
its own PreCompact. SMARTCOMPACT_DEPTH is set in the child's environment before it is spawned; if
this process finds it already set on entry, it does not spawn a second generation at all.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import mapfile, occupancy, runlog, settings, state, transcript  # noqa: E402

RITUAL_NAME = "ritual.md"
BOUNDARIES_NAME = "boundaries.jsonl"
MAP_NAME = "map.md"

# The pseudo-thread the fallback skeleton writes under. Not a name a real
# thread could collide with by accident: _safe_thread_name never produces a
# bare word this short without hyphens unless the input already was one.
FALLBACK_THREAD = "unattended"

# Closed and Pi's, per ritual.md. A disposition outside this set is not a
# fifth option, it is a malformed answer, and is coerced to the safe default
# rather than trusted verbatim.
KNOWN_DISPOSITIONS = {"continue", "park", "close", "fork", "escalate"}
DEFAULT_DISPOSITION = "continue"

# A sub-agent answering with more threads than this is answering with noise,
# not judgement. Sliced rather than refused, so a merely-verbose answer still
# produces a usable ritual run instead of falling all the way back.
MAX_THREADS = 100

DEFAULT_TIMEOUT_S = 90.0

FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _plugin_root():
    """Where this plugin's own files sit. Mirrors hooks/lib/settings.py's own
    _plugin_root: CLAUDE_PLUGIN_ROOT from the environment if a real client set
    it, otherwise this file's own position, one directory above hooks/ rather
    than settings.py's two, since this file lives directly under hooks/ and
    settings.py lives one directory deeper under hooks/lib/.
    """
    from_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[1]


def _claude_bin():
    """The executable this hook spawns as the sub-agent. SMARTCOMPACT_CLAUDE_BIN
    exists only so a test can point this at a stub instead of a real `claude`;
    nothing this plugin ships ever sets it."""
    return os.environ.get("SMARTCOMPACT_CLAUDE_BIN", "claude")


def _timeout_s():
    """The subprocess timeout, 90 seconds unless SMARTCOMPACT_SUBPROCESS_TIMEOUT_S
    overrides it. The override exists for tests: a suite that waited out a real
    90-second timeout to prove one fires would be a suite nobody runs locally."""
    raw = os.environ.get("SMARTCOMPACT_SUBPROCESS_TIMEOUT_S")
    try:
        value = float(raw)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    return DEFAULT_TIMEOUT_S


def _read_ritual():
    """ritual.md's own text, or a short stand-in if this plugin's copy cannot be read.

    A missing ritual.md should not be why the sub-agent gets no prompt at all;
    it should be why the prompt says so plainly instead of silently degrading.
    """
    path = _plugin_root() / RITUAL_NAME
    try:
        text = path.read_text(encoding="utf-8")
        if text.strip():
            return text
    except OSError:
        pass
    return f"({path} could not be read; no ritual instructions were available for this run.)"


def _measurement(transcript_path, project_dir):
    """(occupancy, zone): the same two numbers zone.py reports, computed the
    same way, so boundaries.jsonl never disagrees with the turn-end advisory
    about what a session's occupancy was. Every function this calls already
    degrades to a safe default on its own, including on a missing or
    mid-write transcript, so nothing here needs its own guard.

    The trigger comes from settings.trigger, which prefers what this project
    has been observed compacting at over what is configured. The line this
    function's caller then appends to boundaries.jsonl is what a later run
    reads to make that measurement, so the zone recorded here is also what
    sharpens the next one."""
    value = occupancy.occupancy(transcript.last_usage(transcript_path))
    zone_name = occupancy.zone(value, settings.trigger(project_dir), *settings.thresholds())
    return value, zone_name


def _record_boundary(project_dir, trigger, value, zone_name, session_id):
    """One JSON line appended to boundaries.jsonl. Always attempted first and
    unconditionally, so a boundary is on record even if this hook is killed,
    or the rest of this file raises, immediately afterward."""
    line = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trigger": trigger,
        "occupancy": value,
        "zone": zone_name,
        "session_id": session_id,
    }
    state.append(project_dir / BOUNDARIES_NAME, json.dumps(line) + "\n")


def _timestamp_suffix():
    """The <datetime> half of hnd.<thread>--<datetime>.md, matching the shape
    every fixture and hook already uses: compact, colon-free, UTC."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_thread_name(raw):
    """A thread name safe to drop into a filename. Mirrors hooks/lib/state.py's
    own _slug: a sub-agent's answer is untrusted the moment one of its fields
    becomes a path component, exactly the way a session id is in zone.py, so
    this never passes one through unslugified."""
    collapsed = re.sub(r"[^A-Za-z0-9]+", "-", str(raw)) if raw else ""
    slug = collapsed.strip("-").lower()
    return slug or "thread"


def _handoff_filename(thread_name, suffix):
    return f"{mapfile.HANDOFF_PREFIX}{thread_name}--{suffix}{mapfile.HANDOFF_SUFFIX}"


def _render_handoff(thread_name, disposition, objective, phase, state_text, next_step, pointers):
    """The handoff body, per ritual.md's schema plus its Disposition field.

    Always renders the six-field shape and always marks the disposition
    undecided: this function is the one place that invariant is enforced, so
    it holds even if a future caller forgets to ask for it, which is exactly
    the failure this exists to rule out for the sub-agent's own claims.
    """
    disposition = disposition if disposition in KNOWN_DISPOSITIONS else DEFAULT_DISPOSITION
    pointer_lines = "\n".join(f"- {p}" for p in pointers) if pointers else "- (none given)"
    return (
        f"# Handoff: {thread_name}\n\n"
        f"Disposition: {disposition} (proposed, undecided)\n\n"
        f"## Objective\n\n{objective or '(none given)'}\n\n"
        f"## Phase\n\n{phase or '(none given)'}\n\n"
        f"## State\n\n{state_text or '(none given)'}\n\n"
        f"## Next step\n\n{next_step or '(none given)'}\n\n"
        f"## Pointers\n\n{pointer_lines}\n"
    )


def _build_prompt(ritual_text, transcript_path, map_text, custom_instructions):
    """ritual.md's own text plus this run's situational inputs. The ritual is
    the instructions; everything appended here is context the instructions
    refer to but cannot know in advance."""
    lines = [
        ritual_text,
        "",
        "---",
        "",
        "You are running the unattended consumer above: steps 1 to 4 and 6 to 9, step 5 suppressed.",
        f"Transcript to read: {transcript_path or '(none given)'}",
        "",
        "Existing map.md:",
        map_text if map_text.strip() else "(none on disk yet)",
    ]
    if custom_instructions:
        lines += ["", f"The user's own instructions for this compaction: {custom_instructions}"]
    lines += [
        "",
        "Return nothing but the single fenced ```json block ritual.md describes above. Write no file.",
    ]
    return "\n".join(lines)


def _spawn(prompt, cwd):
    """The sub-agent's stdout on a clean exit, or None for every way this can fail.

    SMARTCOMPACT_DEPTH is set in the child's own environment, never in this
    process's: main()'s own guard reads it from os.environ on entry, so a
    grandchild inheriting it here is what stops a third generation, without
    this process's environment ever changing for anything else it does.
    """
    env = dict(os.environ)
    env["SMARTCOMPACT_DEPTH"] = "1"
    try:
        result = subprocess.run(
            [_claude_bin(), "-p"],
            input=prompt,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=_timeout_s(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _extract_json(text):
    """The last fenced ```json block in text, parsed, or a bare parse of the
    whole text, or None. Fence content is captured by finding the closing
    fence, never by brace-matching: a non-greedy `\\{.*?\\}` would stop at the
    first inner `}` of any nested object, truncating exactly the shape this
    is meant to read. The last fence wins over the first, so a preamble
    sentence in front of the block cannot shadow a perfectly good answer.
    """
    if not isinstance(text, str):
        return None
    fences = FENCE.findall(text)
    candidates = [fences[-1]] if fences else []
    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalized_threads(parsed):
    """A list of clean thread dicts, or None if the answer's shape cannot be trusted at all.

    None is reserved for a structurally broken answer: no "threads" key, or a
    "threads" that is not a list. A list that is merely empty, or whose
    entries are individually messy, is still usable: a bad row is repaired
    field by field rather than discarding the whole run over one of them,
    the same generosity mapfile.parse extends to a hand-edited map.md.
    """
    if not isinstance(parsed, dict):
        return None
    threads = parsed.get("threads")
    if not isinstance(threads, list):
        return None
    normalized = []
    for entry in threads[:MAX_THREADS]:
        if not isinstance(entry, dict):
            continue
        pointers = entry.get("pointers")
        normalized.append(
            {
                "thread": _safe_thread_name(entry.get("thread")),
                "disposition": entry.get("disposition"),
                "objective": str(entry.get("objective") or ""),
                "phase": str(entry.get("phase") or ""),
                "state": str(entry.get("state") or ""),
                "next_step": str(entry.get("next_step") or ""),
                "pointers": [str(p) for p in pointers] if isinstance(pointers, list) else [],
            }
        )
    return normalized


def _write_threads(project_dir, threads, suffix):
    """Every thread's handoff, written via state.write_atomic. Returns
    {thread: handoff_filename}, only for threads that actually wrote, so a
    write failure quietly drops a thread from the map rebuild that follows
    rather than recording a handoff that is not actually on disk."""
    written = {}
    for entry in threads:
        filename = _handoff_filename(entry["thread"], suffix)
        body = _render_handoff(
            entry["thread"],
            entry["disposition"],
            entry["objective"],
            entry["phase"],
            entry["state"],
            entry["next_step"],
            entry["pointers"],
        )
        if state.write_atomic(project_dir / filename, body):
            written[entry["thread"]] = filename
    return written


def _rebuild_map(project_dir, touched):
    """map.md, whole. Step 8 of the ritual, and the only place this file is written.

    A thread this run did not touch keeps its existing row untouched, and a
    thread this run did touch lands at attention 0, because touching it here
    means a fresh handoff was just written for it.

    This is the sole writer, ruled 2026-08-16. A session-end hook was built
    and then removed rather than kept alongside this one: both rewrote the
    file whole, so neither could corrupt it, but two sessions in one project
    could still race and drop a thread from whichever map lost.
    """
    map_path = project_dir / MAP_NAME
    old_text = ""
    if map_path.is_file():
        try:
            old_text = map_path.read_text(encoding="utf-8")
        except OSError:
            old_text = ""
    rows = mapfile.parse(old_text)
    for thread, filename in touched.items():
        rows[thread] = (filename, 0)
    state.write_atomic(map_path, mapfile.render(rows))


def _touched_files(cwd):
    """Best-effort working-tree changes at fallback time, or a note that none could be read.

    git is the one external program this file reaches for, and only from the
    fallback path: a plugin that shelled out on every successful ritual run
    would make an unrelated tool's absence the reason a normal boundary
    degrades. Any failure here, a missing binary, a non-repository, a
    timeout, reads the same as "nothing to report" rather than raising.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "(unavailable: not a git repository, git not found, or nothing changed)"


def _write_fallback_skeleton(project_dir, cwd, trigger, value, zone_name, reason, suffix):
    """The deterministic fallback: one handoff under a fixed pseudo-thread name,
    always marked undecided, recording exactly what step 1 already measured
    plus a best-effort list of what changed on disk. Used whenever the
    sub-agent is skipped, unavailable, timed out, or answered with nothing
    usable, so the reason always ends up in run.log rather than being
    swallowed.
    """
    body = (
        f"# Handoff: {FALLBACK_THREAD}\n\n"
        f"Disposition: {DEFAULT_DISPOSITION} (proposed, undecided)\n\n"
        "## Objective\n\n"
        "(fallback record: the ritual's sub-agent did not characterise this session)\n\n"
        "## Phase\n\n"
        f"Unattended fallback. Reason: {reason}\n\n"
        "## State\n\n"
        f"timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"trigger: {trigger}\n"
        f"occupancy: {value}\n"
        f"zone: {zone_name}\n\n"
        "## Next step\n\n"
        "Run the by-hand ritual to characterise this session's real threads.\n\n"
        "## Pointers\n\n"
        f"Files touched (git status --porcelain):\n{_touched_files(cwd)}\n"
    )
    filename = _handoff_filename(FALLBACK_THREAD, suffix)
    if state.write_atomic(project_dir / filename, body):
        _rebuild_map(project_dir, {FALLBACK_THREAD: filename})
    runlog.record("before-compact", "skeleton", detail=reason)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return

    cwd = payload.get("cwd")
    if not cwd:
        return

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    trigger = payload.get("trigger")
    custom_instructions = payload.get("custom_instructions")

    project_dir = state.project_dir(cwd)
    value, zone_name = _measurement(transcript_path, project_dir)
    _record_boundary(project_dir, trigger, value, zone_name, session_id)  # first and always

    suffix = _timestamp_suffix()

    if os.environ.get("SMARTCOMPACT_DEPTH"):
        reason = "reentrant: SMARTCOMPACT_DEPTH already set, not spawning a second generation"
        _write_fallback_skeleton(project_dir, cwd, trigger, value, zone_name, reason, suffix)
        return

    map_path = project_dir / MAP_NAME
    map_text = ""
    if map_path.is_file():
        try:
            map_text = map_path.read_text(encoding="utf-8")
        except OSError:
            map_text = ""

    prompt = _build_prompt(_read_ritual(), transcript_path, map_text, custom_instructions)
    stdout = _spawn(prompt, cwd)
    if stdout is None:
        _write_fallback_skeleton(
            project_dir, cwd, trigger, value, zone_name, "sub-agent unavailable or timed out", suffix
        )
        return

    threads = _normalized_threads(_extract_json(stdout))
    if threads is None:
        _write_fallback_skeleton(
            project_dir, cwd, trigger, value, zone_name, "sub-agent returned nothing usable", suffix
        )
        return

    written = _write_threads(project_dir, threads, suffix)
    _rebuild_map(project_dir, written)
    runlog.record("before-compact", "ritual", detail=f"{len(written)} threads")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a materialiser that crashes is worse than one that falls back
        runlog.record("before-compact", "error", detail=repr(exc))
    sys.exit(0)
