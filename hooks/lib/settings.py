"""Where the two threshold sources live, and how one overrides the other.

Claude Code's own settings.json is read-only ground truth for the window
this client compacts against. The shipped soft/hard defaults are the numbers
this plugin ships with; a project or person can override them, but only with
a file this module has already checked, because an unvalidated hand edit
could silently reproduce the exact miscalibration this plugin exists to fix.
"""

import json
import os
from pathlib import Path

from . import occupancy, runlog, state

# The last-resort numbers, used only when the shipped file cannot be read at
# all. They duplicate what `smartcompact.yaml` holds, which is a duplication
# worth paying for exactly once: a hook whose thresholds depend on a file
# being present has no thresholds at all if that file is missing, and a hook
# that abstains for want of a config is worse than one that uses the numbers
# it was ruled with.
FALLBACK_SOFT = 0.60
FALLBACK_HARD = 0.80

# The same name in two places, which is the whole design. Under the plugin
# root it is what this plugin ships and never edits; under the plugin data
# directory it is the copy a person edits, which the shipped one must never
# overwrite.
CONFIG_NAME = "smartcompact.yaml"


def _settings_path():
    """~/.claude/settings.json, resolved fresh on every call so tests can point it elsewhere."""
    return Path(os.path.expanduser("~/.claude/settings.json"))


def auto_compact_window():
    """The autoCompactWindow Claude Code itself will compact against.

    None if the file is missing, unreadable, not JSON, not an object, or the
    key holds anything but a number. Read-only: this file belongs to Claude
    Code, and writing to it would make this plugin's own reads unreliable
    the moment a real release touched the same file at the same time.
    """
    try:
        with open(_settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        value = data.get("autoCompactWindow") if isinstance(data, dict) else None
        return value if isinstance(value, (int, float)) else None
    except Exception:
        return None


BOUNDARIES_NAME = "boundaries.jsonl"


def measured_trigger(project_dir):
    """The trigger this project has actually been observed compacting at, or None.

    `boundaries.jsonl` records the occupancy at every boundary along with what
    caused it, so a project that has compacted automatically even once has
    stated its own trigger and does not need it configured.

    The estimate is the *earliest* automatic fire, not the latest and not the
    mean. The check runs between turns, so a single turn can carry occupancy
    well past the point that armed it: every fire is at or above the trigger,
    and the smallest observed is therefore the closest to it. This is the same
    reasoning the corpus sweep used to derive the reserve in the first place.

    Manual boundaries are ignored. A person compacting when they feel like it
    says nothing about where the client would have forced one.
    """
    if not project_dir:
        return None
    path = Path(project_dir) / BOUNDARIES_NAME
    fires = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict) or record.get("trigger") != "auto":
                    continue
                value = record.get("occupancy")
                if isinstance(value, (int, float)) and value > 0:
                    fires.append(value)
    except OSError:
        return None
    return min(fires) if fires else None


def trigger(project_dir=None):
    """Where this client compacts: measured if it can be, configured otherwise, else None.

    Measurement wins because the configured value can be wrong in a way
    nothing else can detect. `autoCompactWindow` is read from the settings
    file, and a session started with a `--autocompact` flag overrides it
    without writing it down, so the hook would compute a trigger for a window
    this session is not using and report a colour it cannot justify. A
    recorded automatic boundary is not an opinion about the window; it is the
    client stating where it compacts.
    """
    measured = measured_trigger(project_dir)
    if measured:
        return measured
    return occupancy.trigger_point(auto_compact_window())


def _plugin_root():
    """Where this plugin's own files sit, from the environment or from this file's position.

    Claude Code exports `CLAUDE_PLUGIN_ROOT` into every hook subprocess. The
    positional fallback is not merely defensive: it is what makes the tests
    and an in-repo run work, and it holds in a built folder too, because the
    build preserves this file's depth below the plugin root.
    """
    from_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[2]


def _read_config(path):
    """(soft, hard) from one config file, or (None, None, reason) if it does not hold a valid pair."""
    parsed, reason = _parse_flat_yaml(path)
    if parsed is None:
        return None, None, reason
    return _validated(parsed)


def thresholds():
    """(soft, hard): what this plugin ships, unless a validated override replaces it.

    Two files, one shape, read in order. The shipped one under the plugin
    root is the source of the defaults rather than a description of them: if
    the numbers lived only in this module, editing the shipped file would
    change nothing and the file would be a comment pretending to be config.

    A missing override is the common case and stays silent. A present but
    invalid one does not, because a hand edit that quietly falls back with no
    trace is indistinguishable from one that worked, and an unchecked edit is
    how the miscalibration this plugin exists to repair would come back.
    """
    soft, hard = FALLBACK_SOFT, FALLBACK_HARD
    try:
        shipped = _plugin_root() / CONFIG_NAME
        if shipped.is_file():
            got_soft, got_hard, reason = _read_config(shipped)
            if got_soft is not None:
                soft, hard = got_soft, got_hard
            else:
                # The plugin shipping an unreadable config is our defect, not
                # the user's, so it is recorded differently from a bad override.
                runlog.record("thresholds", "invalid-shipped", detail=reason)

        override = state.data_dir() / CONFIG_NAME
        if override.is_file() and override.resolve() != shipped.resolve():
            got_soft, got_hard, reason = _read_config(override)
            if got_soft is not None:
                return got_soft, got_hard
            runlog.record("thresholds", "invalid-override", detail=reason)
    except Exception:
        pass
    return soft, hard


def _parse_flat_yaml(path):
    """{key: value} from flat scalar lines only, or (None, reason) for anything else.

    No YAML parser is assumed present, and nothing this file ships needs
    one: the override format is deliberately restricted to what can be
    checked by hand, so a nested or list-shaped line is a validation failure
    rather than a guess at what a real parser would have made of it.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, f"unreadable: {exc}"

    result = {}
    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line[:1] in (" ", "\t"):
            return None, f"line {lineno}: indentation is not a flat scalar"
        if stripped.startswith("-"):
            return None, f"line {lineno}: list content is not a flat scalar"
        if ":" not in stripped:
            return None, f"line {lineno}: no ':' separator"
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip("'\"")
        if not key or not value:
            return None, f"line {lineno}: empty key or value"
        result[key] = value
    return result, None


def _validated(parsed):
    """(soft, hard, None) as floats, or (None, None, reason) on any of the four ways to fail."""
    if "soft" not in parsed or "hard" not in parsed:
        return None, None, "missing 'soft' or 'hard' key"
    try:
        soft = float(parsed["soft"])
        hard = float(parsed["hard"])
    except (TypeError, ValueError):
        return None, None, f"soft={parsed.get('soft')!r} hard={parsed.get('hard')!r} not numeric"
    if not (0 < soft < 1) or not (0 < hard < 1):
        return None, None, f"soft={soft!r} hard={hard!r} must be strictly between 0 and 1"
    if not soft < hard:
        return None, None, f"soft={soft!r} must be strictly less than hard={hard!r}"
    return soft, hard, None
