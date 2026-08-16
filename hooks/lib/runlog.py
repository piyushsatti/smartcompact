"""One append-only log per project: whether a hook ran, and what happened.

A hook's stdout usually has to stay silent, or be exactly the JSON the
harness expects, so a hook that fails quietly has almost nowhere to say so.
This is that place: every public function elsewhere in this package returns
a default instead of raising, which means a silent failure and a silent
success look identical unless something here writes the difference down.
"""

import os
from datetime import datetime, timezone

from . import state

# Rotate once past 1 MB. This log answers "did a hook fire and what
# happened," not "what happened over the life of the project," so one old
# generation is enough context to keep on hand.
MAX_SIZE = 1024 * 1024


def record(event, outcome, ms=None, detail=None):
    """Append one line to this project's run.log. Never raises; returns bool.

    The project is resolved from the process's own working directory rather
    than a parameter, because every hook this package serves runs with cwd
    already set to the project it fired for (PreCompact's own payload
    carries a matching `cwd` field), and threading that value through every
    call site that might log would spread state.py's one job across the rest
    of the package.
    """
    try:
        path = state.project_dir(os.getcwd()) / "run.log"
        _rotate_if_large(path)
        return state.append(path, _format(event, outcome, ms, detail))
    except Exception:
        return False


def _format(event, outcome, ms, detail):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [stamp, str(event), str(outcome)]
    if ms is not None:
        parts.append(f"{ms}ms")
    if detail is not None:
        parts.append(str(detail))
    return " ".join(parts) + "\n"


def _rotate_if_large(path):
    """Move path to its .1 generation before this write would grow it further.

    os.replace, not os.rename: the destination generation is meant to be
    overwritten every time this fires, and only os.replace makes that
    unconditional on every platform this might run on.
    """
    try:
        if path.exists() and path.stat().st_size > MAX_SIZE:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass
