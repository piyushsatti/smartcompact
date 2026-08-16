#!/usr/bin/env python3
"""Turn-end hook: says how full the window is, only when that gets worse.

Fires on every turn, so it has to stay both cheap and quiet. Cheap comes from
the library underneath: transcript.last_usage reads the tail, never the whole
file. Quiet is this file's own job, because a hook that speaks every turn is
noise nobody reads by the tenth time. The debounce latch is the mechanism:
one file per session, under this project's own corner of the plugin data
directory, holding the last zone actually announced. A rise past that zone
speaks and rewrites the latch. A fall rewrites it silently, so the next rise
speaks again. The same zone twice writes nothing and says nothing.

There is no signal in the hook's own payload for "this is turn one", so the
latch doubles as that signal: no file yet means nothing has been measured for
this session before, and the first measurement always seeds the latch without
speaking. That is deliberate, not an oversight. A session whose first message
already lands past soft, from a large opening paste, should not announce
itself before its user has said a word; it gets folded into whatever the next
rise reports instead.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import occupancy, runlog, settings, state, transcript  # noqa: E402

# Comparable order for the latch. green is never itself announced, so a rise
# out of an unseeded latch and a rise out of green behave the same way.
ZONE_RANK = {"green": 0, "orange": 1, "red": 2}


def _latch_path(cwd, session_id):
    """One file per session, so two sessions in the same project never share a latch."""
    return state.project_dir(cwd) / "zone" / session_id


def _read_latch(path):
    """The zone last announced for this session, or None if nothing has been yet.

    None covers a missing file, an empty one, and content this file did not
    write itself: all three mean there is nothing trustworthy to compare
    against, and re-seeding is the safe response to each.
    """
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if text in ZONE_RANK else None


def _speak(zone_name, value, trigger):
    remaining = max(trigger - value, 0)
    message = f"context is {zone_name}: {value:,} tokens, {remaining:,} short of the trigger"
    print(json.dumps({"systemMessage": message}))


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return

    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not cwd or not session_id or not transcript_path:
        return
    if "/" in session_id or "\\" in session_id:
        # A real session id is a UUID. Refusing anything path-shaped keeps a
        # malformed payload from resolving the latch outside zone/.
        return

    value = occupancy.occupancy(transcript.last_usage(transcript_path))
    if value == 0:
        # Covers a missing or empty transcript and a session's first turn
        # alike: last_usage returns None for both, and occupancy(None) is 0.
        return

    trigger = settings.trigger(state.project_dir(cwd))
    zone_name = occupancy.zone(value, trigger, *settings.thresholds())
    if zone_name is None:
        return  # unanchored: no trigger to justify a colour against

    latch_path = _latch_path(cwd, session_id)
    last_zone = _read_latch(latch_path)

    if last_zone is None:
        # First measurement this session has produced. Seed the latch so a
        # future rise has something to compare against, but say nothing yet.
        state.write_atomic(latch_path, zone_name)
        return

    if zone_name == last_zone:
        return  # already announced; never speak twice for the same zone

    state.write_atomic(latch_path, zone_name)
    if ZONE_RANK[zone_name] > ZONE_RANK[last_zone]:
        _speak(zone_name, value, trigger)
        runlog.record("turn-end", zone_name, detail=f"{value}/{trigger}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a measurement hook that fails is worse than one that abstains
        runlog.record("turn-end", "error", detail=repr(exc))
    sys.exit(0)
