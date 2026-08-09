#!/usr/bin/env python3
"""The folders a build wrote are folders each harness can actually install.

Building is not the proof. A build that writes six folders and puts the Codex
manifest in the OpenCode one exits 0, prints six fingerprints and looks exactly
like a good build, because every failure this design is about is a file in the
wrong place rather than an error anybody raised. So the folders get opened.

What is checked, and why each one costs a release if it is wrong:

| Check | What it costs |
|---|---|
| one folder per name in `targets`, and no others | a harness somebody was promised ships nothing, or a folder ships that nobody asked for |
| the manifest each harness reads, at the path it reads it from | the plugin installs nowhere, or installs and is invisible |
| no other harness's manifest in the folder | two schemas claim one filename, which is the whole reason these are separate folders |
| nothing the harness cannot read | an unread file inside the folder's fingerprint that the record cannot explain |
| every skill exactly one level under skills/ | the same package exposes different skills on different harnesses, with no error anywhere |
| the lock file, parsing, naming its own harness | the folder cannot say what it is or what it was built from |
| nothing named in `exclude`, and no manifest, .git, .github or .claude | development material reaching people who installed a plugin |
| the release record agreeing with every lock file | the one place a person compares folders is a fabrication |

The expected shapes live in `harnesses.py` and are written from the design
rather than read from `scripts/emitters/`, which is what makes this a check
instead of an echo.

Operate:
    python3 .github/checks/shipped.py BUILT_DIR PLUGIN_DIR
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harnesses import LOCK_NAME, NEVER_ANYWHERE, RELEASE_NAME, row  # noqa: E402
from report import Report  # noqa: E402

DEFAULT_TARGETS = ("claude-code",)
MANIFEST_NAME = "foundry.plugin.yaml"
SKILL_NAME = "SKILL.md"


def read_manifest(plugin: Path) -> dict:
    """The plugin's own manifest, read the way the build reads it.

    Only three things are wanted from it and all three decide what the built
    folders should look like: which harnesses were asked for, whether the key
    was written at all, and what the author kept out of the shipped folder.
    """
    raw = yaml.safe_load((plugin / MANIFEST_NAME).read_text()) or {}
    declared = raw.get("targets")
    targets = [str(name).strip() for name in declared] if declared else list(DEFAULT_TARGETS)
    return {
        "targets": targets,
        "declared": declared is not None,
        "exclude": [str(name) for name in (raw.get("exclude") or [])],
    }


def layout(built: Path, targets: list[str], report: Report) -> dict[str, Path]:
    """Where each harness's folder is, which the number of them decides.

    With one harness named, or none, the folder is what `--out` points at,
    because that is what every existing marketplace listing points at too. With
    two or more it holds one folder per harness. Getting this wrong in either
    direction breaks an install that used to work, so the shape is checked
    before anything inside it is.
    """
    if len(targets) == 1:
        if (built / RELEASE_NAME).exists():
            report.wrong(
                f"{RELEASE_NAME} was written for a single harness. One folder is the plugin, "
                "and a release record describes several."
            )
        return {targets[0]: built}

    folders = {target: built / target for target in targets}
    for target, path in folders.items():
        if not path.is_dir():
            report.wrong(f"'{target}' is in 'targets' and {path.name}/ was not written.")
    expected = set(targets) | {RELEASE_NAME}
    for entry in sorted(built.iterdir()):
        if entry.name not in expected:
            report.wrong(
                f"{entry.name} is in the release and no harness asked for it. "
                f"'targets' names {', '.join(targets)}."
            )
    return {target: path for target, path in folders.items() if path.is_dir()}


def check_folder(target: str, folder: Path, manifest: dict, report: Report) -> dict:
    """One harness's folder, against the row written for that harness."""
    shape = row(target)
    where = f"{target}:"

    for path in shape.holds:
        if not (folder / path).exists():
            report.wrong(f"{where} no {path}, which is the file this harness reads to find the plugin.")

    for path in shape.forbidden():
        if (folder / path).exists():
            report.wrong(f"{where} holds {path}, which this harness does not read.")

    if shape.only:
        for entry in sorted(folder.iterdir()):
            if entry.name not in shape.only:
                report.wrong(
                    f"{where} holds {entry.name}, and this folder is copied into a repository "
                    f"somebody else owns. It holds {', '.join(shape.only)} and nothing else."
                )

    for name in NEVER_ANYWHERE:
        for found in sorted(folder.rglob(name)):
            report.wrong(f"{where} holds {found.relative_to(folder)}, which never ships from any build.")

    # A name the harness itself writes is not the author's file surviving
    # `exclude`. The instructions folder writes its own CLAUDE.md, and a
    # repository that excluded its own CLAUDE.md still gets that one.
    for name in manifest["exclude"]:
        if name not in shape.holds and (folder / name).exists():
            report.wrong(f"{where} holds {name}, which the manifest's 'exclude' keeps out of the folder.")

    skills = folder / "skills"
    if skills.is_dir():
        for found in sorted(skills.rglob(SKILL_NAME)):
            if len(found.relative_to(skills).parts) != 2:
                report.wrong(
                    f"{where} {found.relative_to(folder)} is not one level under skills/. "
                    "Some harnesses look one level down and some recurse, so this package "
                    "would expose different skills in different places."
                )

    return check_lock(target, folder, manifest, report)


def check_lock(target: str, folder: Path, manifest: dict, report: Report) -> dict:
    """The record of what went into this folder, which every folder carries.

    A folder that cannot say what it is has nothing to compare against the
    release record beside it, so this is checked before that comparison rather
    than as part of it.
    """
    lock = folder / LOCK_NAME
    if not lock.is_file():
        report.wrong(f"{target}: no {LOCK_NAME}, so this folder cannot say what it was built from.")
        return {}
    try:
        recorded = json.loads(lock.read_text())
    except json.JSONDecodeError as broken:
        report.wrong(f"{target}: {LOCK_NAME} is not valid JSON: {broken}.")
        return {}

    if not recorded.get("contents"):
        report.wrong(f"{target}: {LOCK_NAME} records no 'contents' fingerprint.")
    if manifest["declared"] and recorded.get("target") != target:
        report.wrong(
            f"{target}: {LOCK_NAME} says target {recorded.get('target')!r}. "
            "A folder in a release of several has to name which harness it is for."
        )

    carried = [path for path in folder.rglob("*") if path.is_file() and path.name != LOCK_NAME]
    if not carried:
        report.wrong(f"{target}: the folder holds nothing but its lock file, so it is an empty wrapper.")
    return recorded


def check_release(built: Path, targets: list[str], locks: dict[str, dict], report: Report) -> None:
    """The release record is the one place a person compares the folders.

    It exists so that somebody can see that the Pi folder at a version has no
    MCP server while the Claude Code folder at the same version does. That only
    works if every line of it came from the folder it describes, so each
    fingerprint is read back out of the folder's own lock file.
    """
    path = built / RELEASE_NAME
    if not path.is_file():
        report.wrong(f"no {RELEASE_NAME} beside {len(targets)} folders. Nothing says what the release holds.")
        return
    try:
        release = json.loads(path.read_text())
    except json.JSONDecodeError as broken:
        report.wrong(f"{RELEASE_NAME} is not valid JSON: {broken}.")
        return

    for key in ("plugin", "version", "foundry", "built_with_foundry"):
        if not release.get(key):
            report.wrong(f"{RELEASE_NAME} records no '{key}'.")

    records = {record.get("target"): record for record in release.get("targets", [])}
    if set(records) != set(targets):
        report.wrong(
            f"{RELEASE_NAME} lists {', '.join(sorted(name for name in records if name))} "
            f"and the manifest asked for {', '.join(sorted(targets))}."
        )
    for target, recorded in locks.items():
        listed = records.get(target, {}).get("contents")
        if recorded and listed != recorded.get("contents"):
            report.wrong(
                f"{RELEASE_NAME} says {target} is {listed}, and that folder's {LOCK_NAME} "
                f"says {recorded.get('contents')}. The record and the folder disagree."
            )


def main() -> int:
    built = Path(sys.argv[1]).resolve()
    plugin = Path(sys.argv[2]).resolve()
    manifest = read_manifest(plugin)
    targets = manifest["targets"]
    report = Report()

    folders = layout(built, targets, report)
    locks = {target: check_folder(target, folder, manifest, report) for target, folder in folders.items()}
    if len(targets) > 1:
        check_release(built, targets, locks, report)

    report.finish(f"every folder is one its harness can install: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
