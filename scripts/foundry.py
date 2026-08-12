#!/usr/bin/env python3
"""Fetch the Foundry this plugin declared, then hand over to its build tool.

The one file that is genuinely copied into a plugin repo rather than fetched.
It exists because of a loop: a plugin needs the build tool to fetch Foundry,
and the build tool lives inside Foundry. Something has to be present before
anything is fetched, and this is it.

That is the whole reason it stays this small. It is the only file that ever
needs re-copying by hand across every plugin repo, so it must almost never
change. Anything that might need fixing later belongs inside Foundry, where
one fix reaches everyone.

It reads one line of the manifest, the `foundry:` version, and does not try to
work out what the dependencies need. That is the real build tool's job, and it
will stop with a clear message if this repo's declared version turns out to be
older than something in the tree needs.

Operate:
    python3 scripts/foundry.py build --out dist
    python3 scripts/foundry.py check
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Where Foundry is fetched from. Overridable in two places, because a plugin
# repository that is not on GitHub, or a build with no network, still has to
# work: a `foundry_source:` line in the manifest, and the FOUNDRY_SOURCE
# environment variable, which wins so CI can point at a checkout it already has.
# Git clones a local path as readily as a URL, so either accepts a directory.
DEFAULT_SOURCE = "https://github.com/piyushsatti/foundry.git"
REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "foundry.plugin.yaml"
CACHE = REPO / ".foundry"

VERSION_LINE = re.compile(r"^foundry:\s*['\"]?(\d+\.\d+\.\d+)['\"]?\s*(?:#.*)?$", re.MULTILINE)
SOURCE_LINE = re.compile(r"^foundry_source:\s*['\"]?(\S+?)['\"]?\s*(?:#.*)?$", re.MULTILINE)


def manifest_text() -> str:
    if not MANIFEST.is_file():
        sys.exit(f"no {MANIFEST.name} at {REPO}. Start this repo from the Foundry template.")
    return MANIFEST.read_text()


def declared_version(text: str) -> str:
    match = VERSION_LINE.search(text)
    if not match:
        sys.exit(
            f"{MANIFEST} has no 'foundry:' line with a version on it.\nIt should read like:  foundry: 0.1.0"
        )
    return match.group(1)


def declared_source(text: str) -> str:
    override = os.environ.get("FOUNDRY_SOURCE")
    if override:
        return override
    match = SOURCE_LINE.search(text)
    return match.group(1) if match else DEFAULT_SOURCE


def fetch(version: str, source: str) -> Path:
    """A shallow clone of one tag. Cached, because the tag cannot move."""
    target = CACHE / version
    if (target / "scripts" / "build.py").is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetching Foundry {version} from {source}", flush=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", f"v{version}", source, str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(
            f"could not fetch Foundry {version}.\n"
            f"  Check that tag v{version} exists at {source}\n"
            f"  Point somewhere else with a 'foundry_source:' line in {MANIFEST.name},\n"
            f"  or with the FOUNDRY_SOURCE environment variable. A local directory works.\n\n"
            f"{result.stderr.strip()}"
        )
    return target


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"build", "check"}:
        sys.exit("usage: foundry.py build --out DIR  |  foundry.py check")
    text = manifest_text()
    foundry = fetch(declared_version(text), declared_source(text))
    command = [sys.executable, str(foundry / "scripts" / "build.py"), str(REPO)]
    command += ["--check"] if sys.argv[1] == "check" else sys.argv[2:]
    return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
