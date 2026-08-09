#!/usr/bin/env python3
"""A manifest that names no harness still builds what Foundry built before.

This is the check that has to hold whatever else changes. Every plugin already
shipping was written before `targets` existed, and its manifest says nothing
about harnesses. If that manifest starts producing a different folder, or the
same folder one level down, then every marketplace listing pointing at it
breaks and every `contents` fingerprint already recorded in a lock file moves.
Nothing warns anybody: the build exits 0 and prints a new number.

So two builds of the same source are compared:

| Manifest | Has to produce |
|---|---|
| no `targets` key at all | one folder at `--out`, holding `.claude-plugin/plugin.json`, with no release record and a lock file that mentions no harness |
| `targets: [claude-code]` | the same folder, the same manifest bytes, and the same `contents` fingerprint |

The second row is the byte-level half. `contents` is measured before the lock
file is written, so two builds of one source have to agree on it exactly, and
the only difference the folders may carry is the two lines of record that name
the harness. Anything else means opting in changed what ships, which is the one
thing opting in must never do.

The manifest is edited by renaming two keys rather than by rewriting the file,
so every other byte of it is the byte the author wrote. An unknown top-level
key is ignored by `read_manifest`, which is what makes the rename enough.

Operate:
    python3 .github/checks/defaults.py PLUGIN_DIR
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harnesses import LOCK_NAME, RELEASE_NAME  # noqa: E402
from report import Report  # noqa: E402

MANIFEST_NAME = "foundry.plugin.yaml"
METADATA = Path(".claude-plugin") / "plugin.json"

# What the lock file may gain when the manifest names a harness, and nothing
# else may differ between the two builds.
RECORD_ONLY = {"target", "dropped"}


def rebuilt(plugin: Path, work: Path, name: str, manifest: str) -> Path:
    """One copy of the plugin, with one manifest, built into its own folder."""
    source = work / f"{name}-source"
    shutil.copytree(plugin, source)
    (source / MANIFEST_NAME).write_text(manifest)

    out = work / name
    build = Path(__file__).resolve().parents[2] / "scripts" / "build.py"
    done = subprocess.run(
        [sys.executable, str(build), str(source), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        sys.exit(
            f"the {name} build failed, and it is the same source as the other one:\n\n{done.stderr.strip()}"
        )
    return out


def check_default(out: Path, report: Report) -> dict:
    """The folder at `--out` is the plugin, which is what listings point at."""
    if not (out / METADATA).is_file():
        report.wrong(f"no {METADATA} at {out.name}/, so this is not a folder Claude Code installs.")
    if (out / RELEASE_NAME).exists():
        report.wrong(f"{RELEASE_NAME} was written for a manifest that named no harness.")
    for entry in sorted(path.name for path in out.iterdir() if path.is_dir()):
        if entry == "claude-code":
            report.wrong(
                "the folder was written one level down at claude-code/. With no harness named, "
                "the folder at --out is the plugin, which is what every existing listing points at."
            )

    lock = out / LOCK_NAME
    if not lock.is_file():
        report.wrong(f"no {LOCK_NAME} at {out.name}/.")
        return {}
    recorded = json.loads(lock.read_text())
    for key in sorted(RECORD_ONLY & set(recorded)):
        report.wrong(
            f"{LOCK_NAME} records '{key}' for a manifest that named no harness. "
            "A lock file ships inside the folder, so a new key in it is a change to "
            "what every existing plugin ships."
        )
    return recorded


def check_same(default: Path, named: Path, absent: dict, declared: dict, report: Report) -> None:
    """Naming the harness changes the record and nothing else.

    Byte-for-byte on the manifest, and exact on the fingerprint. `contents` is
    measured before the lock file is written, so two builds of one source have
    no room to disagree about it and a difference is a real difference in what
    the folder holds.
    """
    first, second = default / METADATA, named / METADATA
    if first.is_file() and second.is_file() and first.read_bytes() != second.read_bytes():
        report.wrong(
            f"{METADATA} differs between the two builds. Naming claude-code in 'targets' "
            "changed the file Claude Code reads, and the same plugin now describes itself "
            "two ways."
        )
    if absent.get("contents") != declared.get("contents"):
        report.wrong(
            f"the folders fingerprint differently: {absent.get('contents')} with no harness "
            f"named and {declared.get('contents')} with claude-code named. Opting in changed "
            "what ships, so every pin written against the first stops matching."
        )
    differs = sorted(
        key
        for key in set(absent) | set(declared)
        if key not in RECORD_ONLY and absent.get(key) != declared.get(key)
    )
    if differs:
        report.wrong(
            f"{LOCK_NAME} differs on {', '.join(differs)}, which is more than the record "
            "of which harness this folder is for."
        )


def main() -> int:
    plugin = Path(sys.argv[1]).resolve()
    written = (plugin / MANIFEST_NAME).read_text()
    # An unknown top-level key is ignored, so renaming these two is the whole
    # edit and every other byte stays as the author wrote it.
    silent = re.sub(r"(?m)^(targets|degrade):", r"unused-\1:", written)
    if silent == written:
        print(f"{plugin / MANIFEST_NAME} names no 'targets', so both builds would be the same build.")

    report = Report()
    with tempfile.TemporaryDirectory(prefix="foundry-defaults-") as scratch:
        work = Path(scratch)
        default = rebuilt(plugin, work, "no-targets", silent)
        named = rebuilt(plugin, work, "claude-code-named", silent + "\ntargets:\n  - claude-code\n")

        absent = check_default(default, report)
        declared = json.loads((named / LOCK_NAME).read_text()) if (named / LOCK_NAME).is_file() else {}
        check_same(default, named, absent, declared, report)

    report.finish("a manifest naming no harness builds exactly what naming claude-code builds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
