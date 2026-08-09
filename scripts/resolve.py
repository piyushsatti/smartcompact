#!/usr/bin/env python3
"""Work out everything a plugin needs, and refuse to guess when it is unclear.

Runs inside a plugin repository, not inside Foundry. Reads that repo's
`foundry.plugin.yaml`, walks whatever it depends on, and returns one settled
answer: which Foundry version applies, which dependencies are in play, and the
fingerprint of each. `build.py` turns that answer into a shipped folder.

Why this exists: once plugins live in separate repositories, "which version of
the shared thing am I getting" stops being answerable by looking at the
directory layout. This answers it once, when the plugin is published, and
writes the answer down. Nothing is resolved on a user's machine.

The three rules it enforces, and why each one:

  Foundry version      A plugin declares the OLDEST Foundry it works with. The
                       answer is the newest version anyone actually asked for,
                       never newer. So a build can never quietly land on a
                       version nobody requested.

  Foundry major        A major version bump is the only signal that something
                       breaks. If a plugin needs a major this tooling is not,
                       the build stops and says which migration to read.

  Dependency pins      Two dependencies wanting different builds of the same
                       third thing is a real disagreement with no correct
                       answer. It stops and names both sides. It never picks
                       the newer one, because nobody is watching to catch it.

Operate:
    python3 resolve.py [PLUGIN_DIR] [--out lock.json] [--print]

Exit 0 when everything resolves, 1 on any unresolvable disagreement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

FOUNDRY_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = FOUNDRY_ROOT / "VERSION"
MIGRATIONS_DIR = "docs/migrations"

MANIFEST_NAME = "foundry.plugin.yaml"

# Manifest fields that describe the plugin to whoever installs it. They are
# carried through untouched and land in the plugin metadata the build writes.
METADATA_KEYS = ("description", "author", "homepage", "license", "keywords")

# The four content directories a plugin repository holds, and the four a
# dependency may hand over. Named here rather than in `build.py` because both
# halves of the tool need the same list from the same place: the build fences a
# dependency to them, and every emitter declares which of them its target can
# represent. `build.py` still exports it as `CONTENT_DIRS`.
CONTENT_KINDS = ("skills", "agents", "commands", "hooks")

# Everything an emitter can be asked to carry, and the whole vocabulary a
# `degrade` block may name. The two beyond the content directories are not
# directories at all: `mcp` is the plugin's own `mcp.json`, and `allowed-tools`
# is a field inside a skill file that one harness reads and the rest discard.
KINDS = CONTENT_KINDS + ("mcp", "allowed-tools")

# What a manifest that never mentions `targets` gets. This is exactly what
# Foundry built before targets existed, so an existing plugin keeps building
# the same folder in the same place without its owner touching anything.
DEFAULT_TARGETS = ("claude-code",)

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
NAME_RE = re.compile(r"^[a-z0-9._-]+$")
MOVING_TARGETS = {"latest", "current", "head", "*", "main", "master"}

# Never part of what a plugin ships, so never part of its fingerprint.
#
# `.foundry` is the cache the bootstrap stub writes when it fetches a Foundry
# release, and it is here because a pin has to mean the same thing on two
# machines. Without it the fingerprint of a plugin's checkout depends on whether
# that checkout has ever been built and which Foundry versions it happens to
# have cached, so the same source pins differently everywhere and the advice to
# pin against a clean checkout describes a state no built repository can return
# to. It is in `NEVER_SHIP` for the separate reason that it was being copied
# into every folder, eight megabytes of Foundry's own source inside each one.
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".claude", ".github", ".foundry"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {".DS_Store", MANIFEST_NAME}


class ResolveError(Exception):
    """Something could not be settled. The message is the whole report."""


# ------------------------------------------------------------ version numbers
def parse_version(value: str, where: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(str(value).strip())
    if not match:
        raise ResolveError(
            f"{where}: '{value}' is not a version number.\n"
            f"  Expected three numbers separated by dots, like 1.4.2."
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def foundry_version() -> str:
    """The version of the Foundry this tooling came from."""
    if not VERSION_FILE.is_file():
        raise ResolveError(
            f"missing {VERSION_FILE}.\n"
            f"  The build tool ships as part of Foundry, so it should always know\n"
            f"  which Foundry it is. This copy does not, which means it was moved\n"
            f"  out of a Foundry release instead of fetched as one."
        )
    return VERSION_FILE.read_text().strip()


# ---------------------------------------------------------------- fingerprint
def fingerprint(root: Path) -> str:
    """A short, stable name for the exact contents of a folder.

    Sorted file paths and their bytes, hashed together, so a rename counts as a
    change and file order never does. Same method Go uses for module contents.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
            continue
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


# ------------------------------------------------------------------- manifest
def read_targets(raw: dict, path: Path) -> tuple[list[str], bool]:
    """Which harnesses this plugin is built for, and whether it said so.

    Whether a name is one Foundry can emit is not decided here. This module
    sits below the emitters and must not import them, so the shape is checked
    here and the name is checked where the emitter is looked up.

    The second return value is whether the key was written at all, because a
    manifest that never mentions targets has to keep producing the exact bytes
    it produced before the key existed, lock file included.
    """
    raw_targets = raw.get("targets")
    if raw_targets is None:
        return list(DEFAULT_TARGETS), False

    if not isinstance(raw_targets, list):
        raise ResolveError(
            f"{path}: 'targets' should be a list of harness names.\n  targets:\n    - {DEFAULT_TARGETS[0]}"
        )
    if not raw_targets:
        raise ResolveError(
            f"{path}: 'targets' is empty, so this build would write nothing.\n"
            f"  Either name at least one harness, or delete the key and get\n"
            f"  {DEFAULT_TARGETS[0]}, which is what Foundry built before targets existed."
        )

    targets: list[str] = []
    for index, entry in enumerate(raw_targets):
        name = str(entry).strip()
        if not name:
            raise ResolveError(f"{path}: targets[{index}] is empty. Name a harness or remove the line.")
        if name not in targets:
            targets.append(name)
    return targets, True


def read_degrade(raw: dict, targets: list[str], path: Path) -> dict[str, list[str]]:
    """Losses the author pre-authorised, as a map of target to a list of kinds.

    A kind that a target cannot represent stops the build unless it is named
    here. Writing it down is deliberately more work than deleting the target,
    because a diminished package should be a decision somebody made.
    """
    raw_degrade = raw.get("degrade") or {}
    if not isinstance(raw_degrade, dict):
        raise ResolveError(
            f"{path}: 'degrade' should be a map of harness name to a 'drop' list.\n"
            f"  degrade:\n    {targets[0]}:\n      drop: [hooks]"
        )

    degrade: dict[str, list[str]] = {}
    for raw_target, block in raw_degrade.items():
        target = str(raw_target).strip()
        if target not in targets:
            raise ResolveError(
                f"{path}: 'degrade.{target}' waives a loss on a harness that is not built.\n"
                f"  targets: {', '.join(targets)}\n\n"
                f"  A waiver nobody reads does nothing, and a misspelled name here reads\n"
                f"  as a waiver that was written. Fix the name, or add {target} to 'targets',\n"
                f"  or delete the block."
            )
        if not isinstance(block, dict) or "drop" not in block:
            raise ResolveError(
                f"{path}: 'degrade.{target}' should be a block holding a 'drop' list.\n"
                f"  degrade:\n    {target}:\n      drop: [hooks]"
            )
        dropped = block["drop"] or []
        if not isinstance(dropped, list):
            raise ResolveError(f"{path}: 'degrade.{target}.drop' should be a list of kinds.")
        kinds: list[str] = []
        for entry in dropped:
            kind = str(entry).strip()
            if kind not in KINDS:
                raise ResolveError(
                    f"{path}: 'degrade.{target}.drop' names '{kind}', which is not a kind.\n"
                    f"  A kind is one of: {', '.join(KINDS)}."
                )
            if kind not in kinds:
                kinds.append(kind)
        degrade[target] = kinds
    return degrade


def read_manifest(plugin_dir: Path) -> dict:
    path = plugin_dir / MANIFEST_NAME
    if not path.is_file():
        raise ResolveError(
            f"{plugin_dir}: no {MANIFEST_NAME} here.\n"
            f"  Every plugin repository has one at its root. Start from the\n"
            f"  Foundry template if this repository does not."
        )
    raw = yaml.safe_load(path.read_text()) or {}

    name = str(raw.get("id", "")).strip()
    if not name:
        raise ResolveError(f"{path}: needs an 'id'.")
    if not NAME_RE.match(name):
        raise ResolveError(
            f"{path}: id '{name}' has characters that are not allowed.\n"
            f"  Use lowercase letters, numbers, dots, dashes and underscores only."
        )

    if "foundry" not in raw:
        raise ResolveError(
            f"{path}: needs a 'foundry' version.\n"
            f"  This is the oldest Foundry the plugin works with. A plugin takes\n"
            f"  all of Foundry or none of it, so one version is the whole answer."
        )

    requires = raw.get("requires") or {}
    dependencies = []
    for index, entry in enumerate(requires.get("plugins") or []):
        where = f"{path}: requires.plugins[{index}]"
        if not isinstance(entry, dict):
            raise ResolveError(f"{where} should be a block with 'id', 'pin' and 'path'.")
        for key in ("id", "pin", "path"):
            if key not in entry:
                raise ResolveError(f"{where} is missing '{key}'.")
        pin = str(entry["pin"]).strip()
        if pin.lower() in MOVING_TARGETS:
            raise ResolveError(
                f"{where}: pin is '{pin}', which moves.\n"
                f"  A pin names one exact build and never changes meaning. Use a\n"
                f"  fingerprint. Following a moving target is how a plugin ends up\n"
                f"  shipping against something it was never built with."
            )
        dependencies.append(
            {
                "id": str(entry["id"]),
                "pin": pin,
                "path": (plugin_dir / str(entry["path"])).resolve(),
                "take": entry.get("take") or {},
            }
        )

    targets, targets_declared = read_targets(raw, path)
    degrade = read_degrade(raw, targets, path)

    manifest = {
        "id": name,
        "version": str(raw.get("version", "0.0.0")),
        "foundry_minimum": str(raw["foundry"]).strip(),
        "dependencies": dependencies,
        "provides": raw.get("provides") or {},
        "exclude": raw.get("exclude") or [],
        "targets": targets,
        "targets_declared": targets_declared,
        "degrade": degrade,
        "root": plugin_dir,
        "manifest_path": path,
    }
    for key in METADATA_KEYS:
        if raw.get(key):
            manifest[key] = raw[key]
    return manifest


def collect(plugin_dir: Path) -> list[dict]:
    """The plugin plus everything it depends on, each read once.

    Depth-first, tracking the path taken, so a cycle is reported as the actual
    loop rather than as a stack overflow.
    """
    found: dict[str, dict] = {}
    order: list[dict] = []

    def walk(directory: Path, trail: list[str]) -> None:
        manifest = read_manifest(directory)
        name = manifest["id"]
        if name in trail:
            loop = " needs ".join(trail[trail.index(name) :] + [name])
            raise ResolveError(
                f"DEPENDENCY LOOP.\n\n  {loop}\n\n  Break the loop; nothing can be built through it."
            )
        if name in found:
            return
        found[name] = manifest
        order.append(manifest)
        for dependency in manifest["dependencies"]:
            if not dependency["path"].is_dir():
                raise ResolveError(
                    f"{manifest['manifest_path']}: cannot find {dependency['id']} at "
                    f"{dependency['path']}.\n"
                    f"  Check the path, or fetch the dependency before building."
                )
            walk(dependency["path"], trail + [name])

    walk(plugin_dir, [])
    return order


# ---------------------------------------------------------------------- rules
def check_foundry_major(manifests: list[dict], running: str) -> None:
    running_major, _, _ = parse_version(running, str(VERSION_FILE))
    mismatched = []
    for manifest in manifests:
        major, _, _ = parse_version(manifest["foundry_minimum"], f"{manifest['manifest_path']} foundry:")
        if major != running_major:
            mismatched.append((manifest, major))
    if not mismatched:
        return

    report = [
        f"WRONG FOUNDRY GENERATION. This build tool is Foundry {running}.",
        "",
        "A change to the first number means something that used to work no longer",
        "does. It cannot be worked around, only migrated.",
        "",
    ]
    for manifest, major in mismatched:
        # A migration document is named oldest generation first, because it
        # describes what changed going forward and only one of those is ever
        # written. Naming it in the order the two numbers happened to appear
        # would, whenever the plugin is ahead of this tool, point at a document
        # that will never exist, and a refusal with no next step is a bug.
        older, newer = sorted((major, running_major))
        report.append(f"  {manifest['id']} needs Foundry {manifest['foundry_minimum']}")
        report.append(f"    declared in: {manifest['manifest_path']}")
        report.append(f"    read:        {MIGRATIONS_DIR}/foundry-{older}-to-{newer}.md")
    return_error = "\n".join(report)
    raise ResolveError(return_error)


def choose_foundry(manifests: list[dict], running: str) -> str:
    """Newest version anyone asked for. Never newer, never older."""
    running_parsed = parse_version(running, str(VERSION_FILE))
    asked = [(parse_version(m["foundry_minimum"], f"{m['manifest_path']} foundry:"), m) for m in manifests]
    highest, asker = max(asked, key=lambda pair: pair[0])
    chosen = ".".join(str(number) for number in highest)

    if highest > running_parsed:
        raise ResolveError(
            f"FOUNDRY TOO OLD. This build tool is Foundry {running}, but "
            f"{asker['id']} needs at least {chosen}.\n"
            f"  declared in: {asker['manifest_path']}\n\n"
            f"  Build with a newer Foundry, or lower that plugin's requirement.\n"
            f"  Nothing is downgraded automatically."
        )
    return chosen


def check_pins(manifests: list[dict], actual: dict[str, str]) -> None:
    """Nobody may disagree about which build of a dependency is in use."""
    claimed: dict[str, dict[str, list[str]]] = {}
    for manifest in manifests:
        for dependency in manifest["dependencies"]:
            claimed.setdefault(dependency["id"], {}).setdefault(dependency["pin"], []).append(manifest["id"])

    problems = []
    for target in sorted(claimed):
        pins = claimed[target]
        if len(pins) > 1:
            lines = [f"Two different builds of {target} are being asked for:"]
            for pin in sorted(pins):
                lines.append(f"      {pin}  wanted by {', '.join(sorted(pins[pin]))}")
            lines.append("    Only one can ship. Decide which, and update the other.")
            problems.append("\n    ".join(lines))
            continue
        pin = next(iter(pins))
        present = actual.get(target)
        if present is None:
            problems.append(f"{target} is required by {', '.join(sorted(pins[pin]))} but was not found.")
        elif present != pin:
            problems.append(
                f"{', '.join(sorted(pins[pin]))} expects {target} build {pin},\n"
                f"    but the copy here is build {present}.\n"
                f"    Either fetch the expected build, or update the requirement on purpose."
            )
    if problems:
        raise ResolveError(
            "DEPENDENCIES DISAGREE.\n\n    "
            + "\n\n    ".join(problems)
            + "\n\n  Nothing is picked automatically. A disagreement means someone has to\n"
            "  choose, and that choice should be deliberate."
        )


# -------------------------------------------------------------------- resolve
def resolve(plugin_dir: Path) -> dict:
    running = foundry_version()
    manifests = collect(plugin_dir)

    check_foundry_major(manifests, running)
    foundry = choose_foundry(manifests, running)

    actual = {m["id"]: fingerprint(m["root"]) for m in manifests}
    check_pins(manifests, actual)

    root = manifests[0]
    return {
        "plugin": root["id"],
        "version": root["version"],
        "foundry": foundry,
        "foundry_chosen_by": "newest version any dependency asked for",
        "built_with_foundry": running,
        "dependencies": [
            {
                "id": m["id"],
                "version": m["version"],
                "build": actual[m["id"]],
                "foundry_needs_at_least": m["foundry_minimum"],
            }
            for m in sorted(manifests[1:], key=lambda m: m["id"])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Work out everything a plugin needs.")
    parser.add_argument(
        "plugin", nargs="?", type=Path, default=Path.cwd(), help="the plugin repo (default: here)"
    )
    parser.add_argument("--out", type=Path, help="write the answer to this file")
    parser.add_argument("--print", dest="show", action="store_true", help="print the answer")
    args = parser.parse_args()

    try:
        answer = resolve(args.plugin.resolve())
    except ResolveError as problem:
        print(f"\n{problem}\n", file=sys.stderr)
        return 1

    text = json.dumps(answer, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    if args.show:
        print(text, end="")
    if not args.out and not args.show:
        count = len(answer["dependencies"])
        print(f"{answer['plugin']} resolves against Foundry {answer['foundry']}, {count} dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
