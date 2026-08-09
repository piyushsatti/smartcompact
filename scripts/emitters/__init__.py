#!/usr/bin/env python3
"""One plugin, one staged tree, one folder per harness the author asked for.

The seam is after the staged tree is complete and before any lock file is
written. Everything to the left of it is the build tool that already existed:
resolution, fingerprinting, collisions, the `provides` check. Everything to the
right is a per-harness folder, and this package is the whole of it.

Adding a harness means adding one module beside this file and one line to
REGISTRY. Nothing else in Foundry changes, and that is the test of whether the
seam is in the right place.

What this file owns, and what no emitter may re-implement:

  the registry        which module emits which harness
  the loss policy     refuse, or record a pre-authorised drop, and nothing else
  pruning             taking out every kind the harness cannot represent
  the skill depth     one level under skills/, on every harness, always

The loss policy has exactly two outcomes. A declared kind a harness cannot
represent stops the build, naming the kind, the harness and the manifest line,
and both ways forward. Or the author already wrote that loss down under
`degrade.<target>.drop`, and it is printed and written into that harness's lock
file. There is no third outcome and Foundry never decides by itself, which is
the same rule as the build never picking a winner between two dependencies.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import CONTENT_KINDS, KINDS  # noqa: E402

from .contract import (  # noqa: E402
    HOOKS_NAME,
    MCP_NAME,
    SKILL_NAME,
    Cannot,
    Capability,
    EmitError,
    frontmatter,
    hook_rules,
    mcp_servers,
    metadata,
    remove,
    skill_dirs,
    write_json,
)

# Every harness Foundry emits, and the module that emits it. One module may
# serve several harnesses when they share a package shape; each still declares
# its own Capability, because sharing a shape is not sharing a capability.
REGISTRY = {
    "agent-plugins": "agent_plugins",
    "claude-code": "claude_code",
    "codex": "agent_plugins",
    "instructions": "instructions",
    "opencode": "skills_tree",
    "pi": "skills_tree",
}


@dataclass(frozen=True)
class Drop:
    """One kind that will be missing from one harness's folder, on purpose."""

    kind: str
    why: str


@dataclass(frozen=True)
class Loss:
    """What one harness will not carry. Empty is the ordinary case."""

    target: str
    dropped: tuple[Drop, ...]

    def kinds(self) -> tuple[str, ...]:
        return tuple(drop.kind for drop in self.dropped)


# ------------------------------------------------------------------- registry
def known_targets() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))


def load(target: str) -> object:
    """The module that emits this harness, checked against what it claims.

    A registry line and a module's own TARGETS tuple are two statements of the
    same fact, and two statements drift. Reading them against each other here
    turns the drift into a build failure rather than a harness that is listed
    and never emitted.
    """
    if target not in REGISTRY:
        raise EmitError(
            f"NO SUCH TARGET: {target}.\n\n"
            f"  Foundry emits: {', '.join(known_targets())}.\n\n"
            f"  Fix the name in 'targets', or drop the line. Nothing is guessed:\n"
            f"  a misspelled harness that quietly built nothing is how a release\n"
            f"  ships without the folder somebody was promised."
        )
    module = importlib.import_module(f"{__name__}.{REGISTRY[target]}")
    if target not in getattr(module, "TARGETS", ()):
        raise EmitError(
            f"{module.__name__} is registered for {target} but does not claim it.\n"
            f"  Its TARGETS are: {', '.join(getattr(module, 'TARGETS', ()))}.\n"
            f"  This is a Foundry defect, not a problem with the plugin."
        )
    return module


def capability(target: str) -> Capability:
    """What this harness can and cannot carry, checked for completeness.

    A capability that answers for only some kinds is refused here rather than
    at the moment the unanswered kind is declared, so the gap is found on any
    build and not only on the one plugin that happens to hold that kind.
    """
    module = load(target)
    declared = getattr(module, "CAPABILITIES", {})
    if target not in declared:
        raise EmitError(
            f"{module.__name__} declares no CAPABILITIES entry for {target}.\n"
            f"  This is a Foundry defect, not a problem with the plugin."
        )
    answer = declared[target]
    if answer.missing():
        raise EmitError(
            f"{module.__name__} does not say whether {target} carries "
            f"{', '.join(answer.missing())}.\n"
            f"  Every kind is answered either in 'carries' or in 'cannot'.\n"
            f"  This is a Foundry defect, not a problem with the plugin."
        )
    if answer.doubled():
        raise EmitError(
            f"{module.__name__} says {target} both carries and cannot carry "
            f"{', '.join(answer.doubled())}.\n"
            f"  This is a Foundry defect, not a problem with the plugin."
        )
    return answer


# --------------------------------------------------------- what was declared
def declared_kinds(tree: Path) -> dict[str, list[str]]:
    """Every kind the staged tree actually holds, and what it holds of each.

    Read from the tree rather than from the manifest, because the tree is what
    ships: content taken from a dependency counts exactly as much as content
    the plugin wrote. Names are carried along so a refusal can point at the
    thing rather than at its category.

    A dot file does not declare a kind. An empty content directory kept alive
    by a placeholder is an empty directory, and refusing a build over one would
    make the Foundry template unbuildable on the day it is copied.
    """
    found: dict[str, list[str]] = {}
    for kind in CONTENT_KINDS:
        directory = tree / kind
        if not directory.is_dir():
            continue
        items = sorted(entry.name for entry in directory.iterdir() if not entry.name.startswith("."))
        if items:
            found[kind] = items

    servers = mcp_servers(tree)
    if servers:
        found["mcp"] = sorted(servers)

    restricted = [
        skill.name for skill in skill_dirs(tree) if frontmatter(skill / SKILL_NAME).get("allowed-tools")
    ]
    if restricted:
        found["allowed-tools"] = sorted(restricted)
    return found


def check_skills_are_one_level_deep(tree: Path, manifest_path: Path) -> None:
    """A skill directory sits exactly one level under skills/, on every harness.

    Some harnesses look exactly one level down and some recurse. A grouping
    directory therefore ships intact on part of the list and makes every skill
    beneath it invisible on the rest, with no error raised anywhere, so the
    author sees a working install and the user sees nothing. Refusing is the
    only outcome that reaches the person who can fix it.

    This is checked once, on the neutral tree, and stops the whole build rather
    than one harness: the same package must expose the same skills everywhere.
    """
    skills = tree / "skills"
    if not skills.is_dir():
        return
    deep = sorted(
        str(path.relative_to(tree))
        for path in skills.rglob(SKILL_NAME)
        if len(path.relative_to(skills).parts) != 2
    )
    if not deep:
        return
    raise EmitError(
        "SKILL NESTED TOO DEEP.\n\n  "
        + "\n  ".join(deep)
        + f"\n\n  Declared by {manifest_path}. A skill directory sits exactly one level\n"
        "  under skills/. Some harnesses look one level down and some recurse, so a\n"
        "  nested skill installs on part of the list and is invisible on the rest\n"
        "  with no error anywhere.\n\n"
        "  Either move each one up to skills/<name>/, or fold the grouping into the\n"
        "  name, as skills/<group>-<name>/."
    )


# ----------------------------------------------------------- the loss policy
def assess(target: str, declared: dict[str, list[str]], waived: list[str], manifest_path: Path) -> Loss:
    """Refuse, or record what the author already agreed to lose. Nothing else.

    Every kind-level loss can be waived, including the ones that gut a package:
    the refusal itself names the waiver, so an author who reads it and decides
    the diminished folder is still worth shipping has a way to say so. What
    cannot be waived is a loss that changes behaviour rather than reducing it,
    a guard that fails open or a matcher that matches everything, and those
    depend on what is inside a file rather than on its kind. The emitter raises
    those itself, while it is looking at the content.
    """
    answer = capability(target)
    refused: list[tuple[str, list[str], str]] = []
    dropped: list[Drop] = []

    for kind in KINDS:
        if kind not in declared or kind not in answer.cannot:
            continue
        why = answer.cannot[kind].why
        if kind in waived:
            dropped.append(Drop(kind=kind, why=why))
        else:
            refused.append((kind, declared[kind], why))

    if refused:
        raise EmitError(refusal(target, manifest_path, refused))
    return Loss(target=target, dropped=tuple(dropped))


def name_item(kind: str, item: str) -> str:
    """Point at the thing, not at its category, in whatever shape it has.

    Three of the six kinds are directories and read as a path. `mcp` names a
    server inside one file. `allowed-tools` is not a thing at all, it is a
    field inside a skill, and calling it `allowed-tools/<skill>` would send the
    author looking for a directory that does not exist.
    """
    if kind == "allowed-tools":
        return f"allowed-tools on skills/{item}"
    return f"{kind}/{item}"


def refusal(target: str, manifest_path: Path, refused: list[tuple[str, list[str], str]]) -> str:
    """Name the kind, the harness, the manifest line, and both ways forward.

    The second way forward is deliberately more work than the first. Deleting a
    harness from 'targets' is one line; writing the loss down is a block. A
    diminished package should feel like a decision, because it is one.
    """
    lines = [f"CANNOT SHIP THIS TO {target.upper()}.", ""]
    for kind, items, why in refused:
        named = ", ".join(name_item(kind, item) for item in items)
        verb = "is" if len(items) == 1 else "are"
        lines.append(f"  {named} {verb} declared in {manifest_path}, and {why}.")
    kinds = ", ".join(kind for kind, _, _ in refused)
    lines += [
        "",
        f"  Either drop {target} from 'targets', or write it down under",
        f"  'degrade.{target}.drop: [{kinds}]' so the loss is on the record.",
    ]
    return "\n".join(lines)


def plan(
    targets: list[str], declared: dict[str, list[str]], degrade: dict[str, list[str]], manifest_path: Path
) -> dict[str, Loss]:
    """One Loss per harness, or the first refusal, decided before anything is written.

    Every harness is assessed before any folder is emitted, so a build that
    cannot ship one of them stops without having written the others. Half a
    release is worse than none: the assets that did appear look complete.
    """
    losses = {target: assess(target, declared, degrade.get(target, []), manifest_path) for target in targets}

    if declared and all(set(loss.kinds()) == set(declared) for loss in losses.values()):
        rows = "\n".join(f"    {target:<16}drops {', '.join(losses[target].kinds())}" for target in targets)
        raise EmitError(
            "NOTHING WOULD SHIP.\n\n"
            f"  Every harness in 'targets' drops everything {manifest_path} declares.\n\n"
            f"{rows}\n\n"
            f"  This plugin holds {', '.join(sorted(declared))} and no named harness carries\n"
            "  any of it, so every folder in the release would be an empty wrapper.\n\n"
            "  Either name a harness that carries what this plugin holds, or stop\n"
            "  declaring the kinds nothing carries."
        )
    return losses


# ------------------------------------------------------------------- emitting
def prune(tree: Path, answer: Capability) -> None:
    """Take out every kind this harness cannot represent, whether declared or not.

    No harness folder may hold a file that harness does not read. An unread
    file is outside whatever that harness validates and inside the folder's
    `contents` fingerprint, so it ships and the record cannot explain why it is
    there. This is the same failure as the author's local settings reaching
    people who installed a plugin.

    Pruning is here rather than in each emitter because it is identical for
    every harness: what differs is the list of kinds, which the emitter already
    declared.
    """
    for kind in answer.cannot:
        if kind in CONTENT_KINDS:
            remove(tree / kind)
        elif kind == "mcp":
            remove(tree / MCP_NAME)
        elif kind == "allowed-tools":
            strip_allowed_tools(tree)


def strip_allowed_tools(tree: Path) -> None:
    """Take `allowed-tools` out of every skill file, leaving the rest untouched.

    The field is rewritten line by line rather than by reloading and re-dumping
    the frontmatter, because a re-dump reformats a file the author wrote and
    every reformatted byte lands in a `contents` fingerprint looking like a
    content change.
    """
    for skill in skill_dirs(tree):
        path = skill / SKILL_NAME
        lines = path.read_text().splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            continue
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is None:
            continue
        kept, index = [], 0
        while index < len(lines):
            line = lines[index]
            if (
                0 < index < closing
                and line.split(":")[0].strip() == "allowed-tools"
                and not line.startswith((" ", "\t"))
            ):
                index += 1
                # A block value continues on the following, more indented lines.
                while index < closing and lines[index].startswith((" ", "\t", "-")):
                    index += 1
                continue
            kept.append(line)
            index += 1
        if len(kept) != len(lines):
            path.write_text("".join(kept))


def run(target: str, manifest: dict, tree: Path) -> None:
    """Turn one copy of the staged tree into one harness's folder, in place.

    Pruning happens first so that an emitter is never handed content its own
    harness cannot carry, which is what keeps every emitter free of loss logic.
    """
    module = load(target)
    prune(tree, capability(target))
    try:
        module.emit(target, manifest, tree)
    except NotImplementedError as gap:
        # A registered harness whose emitter is not written yet. A traceback
        # here would read as a crash in the plugin's own build and name no next
        # step, when the truth is that Foundry cannot do this and the plugin is
        # fine. This disappears the moment every registered emitter is written.
        raise EmitError(
            f"FOUNDRY CANNOT BUILD {target.upper()} YET.\n\n"
            f"  {gap}\n\n"
            f"  This is a Foundry defect, not a problem with the plugin. Either take\n"
            f"  {target} out of 'targets' for now, or build with a Foundry that has it."
        ) from gap


__all__ = [
    "Cannot",
    "Capability",
    "Drop",
    "EmitError",
    "HOOKS_NAME",
    "Loss",
    "MCP_NAME",
    "REGISTRY",
    "SKILL_NAME",
    "assess",
    "capability",
    "check_skills_are_one_level_deep",
    "declared_kinds",
    "frontmatter",
    "hook_rules",
    "known_targets",
    "load",
    "mcp_servers",
    "metadata",
    "plan",
    "prune",
    "run",
    "skill_dirs",
    "write_json",
]
