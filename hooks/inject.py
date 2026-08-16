#!/usr/bin/env python3
"""Session-start hook: points a fresh session at this project's prior state.

Only ever acts on source "compact". Every other source, startup, resume,
clear, fork, means either there is no prior smartcompact state worth reading
back (startup) or the session already carries its own continuity some other
way; injecting this project's state into an unrelated session is worse than
saying nothing.

What it emits is references, never content: a path, and one line on what is
at that path and why it matters right now. The next session explores those
paths itself and rebuilds its own understanding of them, rather than being
handed a summary it cannot check against the source. map.md and each live
handoff are named this way; nothing here reads a handoff's own text.

map.md's own format lives in lib/mapfile.py rather than here, since
between them they are its only reader and its only writer: a markdown table,
one row per live thread, holding that thread's current handoff filename (or
"(none)" if the ritual has never characterised it) and an attention counter.
A thread with no handoff is undecided, and undecided threads are called out
by name so a resuming session knows which ones still owe a decision.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import mapfile, runlog, state  # noqa: E402

CAP = 10_000


def _build_context(project_dir):
    """The additionalContext string, or None if this project holds no state at all."""
    map_path = project_dir / "map.md"
    # Oldest first here; the handoff lines below are built newest first from
    # this same list, because newest is what should survive truncation.
    handoff_paths = sorted(project_dir.glob("hnd.*.md"))
    if not map_path.is_file() and not handoff_paths:
        return None

    lines = [
        "Resuming after a compaction. This project has prior smartcompact state.",
        "The paths below are not summarised: open them to rebuild context.",
    ]

    map_rows = {}
    if not map_path.is_file():
        lines.append(f"{map_path}: no resident map on disk yet; only the handoffs below exist.")
    else:
        try:
            map_text = map_path.read_text(encoding="utf-8")
        except OSError:
            map_text = ""
        if not map_text.strip():
            lines.append(f"{map_path}: exists but is empty or unreadable; treat the map as unknown.")
        else:
            lines.append(f"{map_path}: resident map of live threads, their handoffs, and attention.")
            map_rows = mapfile.parse(map_text)

    undecided = sorted(name for name, (handoff, _attention) in map_rows.items() if handoff is None)
    if undecided:
        lines.append("Undecided, no handoff yet: " + ", ".join(undecided) + ".")

    handoff_lines = []
    for path in reversed(handoff_paths):  # newest first: first choice to keep under the cap
        thread = mapfile.thread_from_handoff_name(path.name)
        handoff_lines.append(f'{path}: live handoff for thread "{thread}".')

    dropped = 0

    def render():
        body = list(lines) + handoff_lines
        if dropped:
            plural = "s" if dropped != 1 else ""
            body.append(
                f"(truncated: {dropped} oldest handoff{plural} dropped to stay under {CAP} characters.)"
            )
        return "\n".join(body)

    text = render()
    while len(text) > CAP and handoff_lines:
        handoff_lines.pop()  # drops the oldest, which sorts last in this newest-first list
        dropped += 1
        text = render()

    return text[:CAP]


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    if payload.get("source") != "compact":
        return

    cwd = payload.get("cwd")
    if not cwd:
        return

    project_dir = state.project_dir(cwd)
    if not project_dir.is_dir():
        return

    context = _build_context(project_dir)
    if context is None:
        return

    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    runlog.record("session-start", "injected", detail=f"{len(context)} chars")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        runlog.record("session-start", "error", detail=repr(exc))
    sys.exit(0)
