"""Where this plugin's durable state lives, and the two ways of touching it.

Exactly one component resolves CLAUDE_PLUGIN_DATA and builds paths under it:
this module. Everything else in hooks/lib asks state.py for a path rather
than reading the environment or joining path segments itself, because a
second path computation that quietly drifts from this one is a bug nobody
notices until two components disagree about where the same file lives.
"""

import os
import re
import tempfile
from pathlib import Path

FALLBACK = "~/.claude/plugins/data/smartcompact/"


def data_dir():
    """Root of this plugin's state: CLAUDE_PLUGIN_DATA, or the documented fallback.

    CLAUDE_PLUGIN_DATA is exported into every hook subprocess but is not
    documented as reaching a skill, so the fallback is what a skill invoked
    by hand actually sees. os.path.expanduser is used instead of Path.home(),
    which can raise when no home directory can be determined; this function
    must not.
    """
    override = os.environ.get("CLAUDE_PLUGIN_DATA")
    if override:
        try:
            return Path(override)
        except (TypeError, ValueError):
            pass
    return Path(os.path.expanduser(FALLBACK))


def project_dir(cwd):
    """This project's own corner of the plugin's one global data directory.

    CLAUDE_PLUGIN_DATA is global per plugin, not per project, so every
    project's state would collide in one map without a key. The key is cwd,
    slugified: lowercased, every run of non-alphanumeric characters collapsed
    to one hyphen, leading and trailing hyphens stripped.
    """
    return data_dir() / "projects" / _slug(cwd)


def write_atomic(path, text):
    """Replace path's contents in one step, or leave path exactly as it was.

    The temp file is created in path's own directory rather than a system
    temp directory, because os.replace is only atomic within a single
    filesystem: a temp file elsewhere could not be swapped in without a copy,
    and a hook killed mid-copy is the torn file this function exists to
    prevent. Every step from mkdir through the final replace sits behind one
    broad catch, because a hook that fails to write is expected and a hook
    that crashes is not.
    """
    path = Path(path)
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None  # renamed away; nothing left for the finally block to clean up
        return True
    except Exception:
        return False
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def append(path, text):
    """text, written once, appended to path. text should carry its own newline.

    A single open-write-close: an append is not the read-modify-write hazard
    write_atomic exists for, so there is no temp file here, only a mode that
    guarantees the write lands after whatever was already there. Creates
    path's parent directory first, the same as write_atomic, since a fresh
    project has none of its state directories yet.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
        return True
    except Exception:
        return False


def _slug(text):
    """Lowercase, hyphen-joined, collision-safe key for an arbitrary path.

    A project directory is arbitrary bytes on disk: spaces, unicode, trailing
    slashes. Anything that is not a letter or digit becomes one hyphen, so
    two paths that differ only in punctuation still key the same, and
    nothing here can produce a leading/trailing hyphen or an empty name for
    os.path to trip on later.
    """
    collapsed = re.sub(r"[^A-Za-z0-9]+", "-", str(text)) if text else ""
    slug = collapsed.strip("-").lower()
    return slug or "unknown"
