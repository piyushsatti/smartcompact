#!/usr/bin/env python3
"""What every emitter module declares, and what it is handed to work with.

An emitter turns the staged neutral tree into one harness's folder. It runs
after resolution, fingerprinting, collision detection and the `provides` check
have all finished, so there is nothing left to decide about content: it may add
files, write the harness's manifest, translate a neutral file into the shape
that harness reads, and delete a neutral file that harness does not read. It
may not resolve, fetch, reorder or reach outside the tree it was given.

A module in this package declares two names and one function:

    TARGETS       the harness names it emits, as a tuple
    CAPABILITIES  one Capability per name in TARGETS
    emit          writes that harness's folder, in place, in the tree given

Everything about loss lives in the framework, never in an emitter. A module
states what its harness cannot represent and why; whether that is a refusal or
a recorded drop is decided once, in `emitters/__init__.py`, from the manifest.

The one thing an emitter does decide is a refusal about content rather than
about kinds: a transport a harness rejects, a matcher a harness ignores, a
blocking hook a harness cannot express. Those depend on what is inside the
file, not on which kind it is, so the emitter raises EmitError itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from resolve import CONTENT_KINDS, KINDS, METADATA_KEYS

# The Agent Plugins 1.0.0 file, at the path that specification names. Emitters
# that read it translate it; emitters whose harness reads it copy it through.
MCP_NAME = "mcp.json"

# The neutral hook declaration. This file never ships anywhere: every harness
# with a hook surface has its own event vocabulary, so an emitter that carries
# hooks translates this and removes it.
HOOKS_NAME = "hooks/hooks.yaml"

SKILL_NAME = "SKILL.md"


class EmitError(Exception):
    """This harness's folder could not be written. The message is the report."""


@dataclass(frozen=True)
class Cannot:
    """One kind a harness cannot represent, and the sentence saying why.

    `why` is read into a refusal as "... is declared in <manifest>, and <why>."
    so write it as a statement about the harness, lowercase, no full stop:
    "Pi has no MCP surface", not "Foundry cannot emit MCP for Pi".
    """

    why: str


@dataclass(frozen=True)
class Capability:
    """What one harness can carry and what it cannot.

    `carries` and `cannot` together name every kind in KINDS, and the framework
    checks that before dispatching. Requiring both, rather than deriving one
    from the other, is what stops a kind added later from being silently
    carried by a harness nobody re-read: the omission is a loud error at build
    time instead of a directory shipping where nothing reads it.
    """

    carries: tuple[str, ...]
    cannot: dict[str, Cannot]

    def missing(self) -> tuple[str, ...]:
        """Kinds this capability answers for neither way."""
        answered = set(self.carries) | set(self.cannot)
        return tuple(kind for kind in KINDS if kind not in answered)

    def doubled(self) -> tuple[str, ...]:
        """Kinds this capability answers for both ways, which cannot be true."""
        return tuple(kind for kind in self.carries if kind in self.cannot)


# ----------------------------------------------------------- shared file work
def write_json(path: Path, payload: dict) -> None:
    """Two-space indent and a trailing newline, everywhere, without exception.

    Every manifest Foundry writes goes through here. Emitters that format their
    own JSON drift apart one release at a time, and the drift lands in a
    `contents` fingerprint where it looks like a content change.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def metadata(manifest: dict) -> dict:
    """Name, version, and whichever descriptive fields the manifest actually set.

    The order is fixed by METADATA_KEYS in `resolve.py` so that two harnesses
    describing the same plugin describe it in the same order. A field the
    author left out is left out here: no emitter invents a value.
    """
    described = {"name": manifest["id"], "version": manifest["version"]}
    for key in METADATA_KEYS:
        value = manifest.get(key)
        if value:
            described[key] = value
    return described


def frontmatter(path: Path) -> dict:
    """The YAML block a markdown content file opens with, or an empty map.

    Anything that is not a map at the top is treated as absent rather than
    refused, because deciding a content file is malformed is the validating
    tools' job and not the build's.
    """
    if not path.is_file():
        return {}
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            loaded = yaml.safe_load("\n".join(lines[1:index])) or {}
            return loaded if isinstance(loaded, dict) else {}
    return {}


def skill_dirs(tree: Path) -> list[Path]:
    """Every skill directory, which is every directory holding a SKILL.md.

    Exactly one level under `skills/`, because the build refuses anything
    deeper before an emitter ever runs.
    """
    skills = tree / "skills"
    if not skills.is_dir():
        return []
    return sorted(path.parent for path in skills.glob(f"*/{SKILL_NAME}"))


def mcp_servers(tree: Path) -> dict:
    """The `mcpServers` map from the plugin's own mcp.json, or an empty map.

    A plugin's MCP servers are always its own. Nothing is ever taken from a
    dependency, so there are never two of these maps to merge.
    """
    payload = read_json(tree / MCP_NAME)
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    return servers if isinstance(servers, dict) else {}


def hook_rules(tree: Path) -> list[dict]:
    """The neutral hook list, in the four-moment vocabulary, or an empty list."""
    path = tree / HOOKS_NAME
    if not path.is_file():
        return []
    loaded = yaml.safe_load(path.read_text()) or []
    return loaded if isinstance(loaded, list) else []


def remove(path: Path) -> None:
    """Take a file or a directory out of a target's folder, if it is there.

    No harness folder may hold a file that harness does not read, so removing
    a neutral file an emitter has just translated is the normal end of the
    translation rather than tidying.
    """
    import shutil

    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


__all__ = [
    "CONTENT_KINDS",
    "Cannot",
    "Capability",
    "EmitError",
    "HOOKS_NAME",
    "KINDS",
    "MCP_NAME",
    "METADATA_KEYS",
    "SKILL_NAME",
    "frontmatter",
    "hook_rules",
    "mcp_servers",
    "metadata",
    "read_json",
    "remove",
    "skill_dirs",
    "write_json",
]
