#!/usr/bin/env python3
"""What each harness's folder has to hold, stated independently of the emitters.

This table says the same thing `scripts/emitters/` says, on purpose, and that
duplication is the only reason it is worth having. A check that asked the
emitters what they write and then confirmed they wrote it would agree with
every change, including a wrong one. So nothing in this directory imports
anything from `scripts/`, and nobody should tidy it into doing so.

Every row was read from the design and the primary sources behind it rather
than from the emitter that satisfies it:

| Harness | Manifest | Read from |
|---|---|---|
| agent-plugins | `plugin.json` at the package root | the published 1.0.0 schema, whose manifest is at the root and not inside a dot directory |
| claude-code | `.claude-plugin/plugin.json` | what Foundry has always written, and the one path that must never move. Its MCP servers and hooks are read from `.mcp.json` and `hooks/hooks.json` (https://code.claude.com/docs/en/plugins-reference) |
| codex | both of the above shapes, root plus `.codex-plugin/plugin.json` | Codex 0.139.0 reads its own overlay, and a Codex that adopted the standard reads the root |
| instructions | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | three harnesses read three names, and two of them read an `@file` import |
| opencode | none of any kind | OpenCode has no package format, no install command and no version |
| pi | none of any kind | Pi has no package format either, and the shape of a `pi` key inside `package.json` was never read from loader source |

The `never` column is the rule that no harness folder may hold a file that
harness does not read. An unread file sits inside the folder's `contents`
fingerprint with nothing to explain why it is there, which is the same failure
as the author's local settings reaching people who installed a plugin.

Two harnesses claiming the same path with different contents is why the outputs
are separate folders at all, so every folder is also checked for the manifests
that belong to the other harnesses. That check is derived rather than typed out,
because typing it four times is four chances to leave one out.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# Every manifest filename Foundry can write, and who reads it. A folder holds
# the ones its own row names and none of the others.
MANIFESTS = {
    "plugin.json": "Agent Plugins 1.0.0, at the package root",
    ".claude-plugin/plugin.json": "Claude Code",
    ".codex-plugin/plugin.json": "Codex from before it adopted the standard",
    "package.json": "Pi",
}


@dataclass(frozen=True)
class Folder:
    """One harness's folder: what has to be in it, and what must not be.

    `only` is set for the one target whose folder is copied into a working tree
    somebody else owns. There a stray file is not an unread file, it is a file
    that lands on top of one of theirs, so that folder is checked against a
    closed list instead of an open one.
    """

    holds: tuple[str, ...] = ()
    never: tuple[str, ...] = ()
    only: tuple[str, ...] = ()

    def forbidden(self) -> tuple[str, ...]:
        """What this row forbids, plus every other harness's manifest."""
        others = tuple(name for name in MANIFESTS if name not in self.holds)
        return tuple(sorted(set(self.never) | set(others)))


HARNESS = {
    # Version 1.0.0 standardises skills and MCP servers and says commands,
    # hooks, agents, rules and LSP servers stay client-specific and are outside
    # it, so a portable folder carrying any of those three carries a directory
    # no client of the standard reads.
    "agent-plugins": Folder(
        holds=("plugin.json",),
        never=("agents", "commands", "hooks"),
    ),
    # Claude Code carries every kind Foundry models, so nothing is ever taken
    # out of this folder. What it forbids is the two neutral names, which it
    # does not read: it reads `.mcp.json` and `hooks/hooks.json`. Neither
    # translated name is in `holds`, because a plugin with no MCP server and no
    # hook is not missing anything. This folder shipped both neutral files
    # unread once, with `claude plugin details` reporting `MCP servers (0)` and
    # `Hooks (0)` while the install reported success.
    "claude-code": Folder(
        holds=(".claude-plugin/plugin.json",),
        never=("mcp.json", "hooks/hooks.yaml"),
    ),
    # Two manifests are the two sides of the release where Codex adopted the
    # standard, and a folder carrying one of them is unreadable on the other
    # side. Codex's own manifest names no agent or command location.
    "codex": Folder(
        holds=("plugin.json", ".codex-plugin/plugin.json"),
        never=("agents", "commands", "hooks"),
    ),
    # Copied into a repository somebody else owns, so this is the one folder
    # checked against a closed list. A stray file here is not an unread file,
    # it is a file that lands on top of one of theirs.
    "instructions": Folder(
        holds=("AGENTS.md", "CLAUDE.md", "GEMINI.md"),
        only=("AGENTS.md", "CLAUDE.md", "GEMINI.md", "foundry.lock.json", "skills", "commands"),
    ),
    # OpenCode reads MCP servers from the user's own opencode.json, which no
    # shipped folder can write, and it has no declarative hook surface.
    "opencode": Folder(
        never=("commands", "hooks", "mcp.json"),
    ),
    # Pi has no MCP surface, no agent surface and no declarative hooks, and it
    # reads a user-invocable prompt unit from prompts/ rather than commands/.
    # It gets no manifest at all: the shape of a `pi` key inside package.json
    # was taken from documentation and never read from loader source, so a
    # guessed manifest is the one thing this folder must not ship.
    "pi": Folder(
        never=("agents", "commands", "hooks", "mcp.json"),
    ),
}

# Present in every folder Foundry writes, whichever harness it is for.
LOCK_NAME = "foundry.lock.json"

# Written beside the folders when there is more than one of them.
RELEASE_NAME = "foundry.release.json"

# Never in any shipped folder, for any harness. The first is the manifest, which
# describes the build and does not ship. The rest are development directories
# that `resolve.py` already leaves outside every fingerprint, which is exactly
# what makes copying one of them invisible in the record.
NEVER_ANYWHERE = ("foundry.plugin.yaml", ".git", ".github", ".claude", "__pycache__")


def row(target: str) -> Folder:
    """The expected folder for one harness, or a refusal naming the next step.

    A target with no row here is not skipped. A check that quietly passes over
    a harness it does not recognise proves nothing about the folder that
    harness ships, and the release goes out with that folder unexamined.
    """
    if target not in HARNESS:
        sys.exit(
            f"this check has no row for the '{target}' harness.\n"
            f"  It knows: {', '.join(sorted(HARNESS))}.\n\n"
            f"  A new harness needs a row in .github/checks/harnesses.py saying which\n"
            f"  manifest its folder holds and what it must not hold. Skipping it here\n"
            f"  would ship that folder with nothing having looked at it."
        )
    return HARNESS[target]
