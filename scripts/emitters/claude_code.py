#!/usr/bin/env python3
"""The folder Claude Code installs: its manifest, its MCP file, its hook file.

Claude Code carries every kind Foundry models, so nothing is ever pruned from
this folder and no plugin ever needs a `degrade.claude-code` block. Carrying a
kind is not the same as copying it through, though, and two of the six arrive
in a neutral shape Claude Code does not read:

    neutral                 Claude Code reads          checked against
    mcp.json                .mcp.json                  the plugins reference
    hooks/hooks.yaml        hooks/hooks.json           the plugins reference

Both were shipped untranslated until this change, and neither failed loudly.
`claude plugin details` on such a folder reports `MCP servers (0)` and
`Hooks (0)` while the install reports success and the two files sit there
unread. That is a silent drop, which is the one outcome the loss policy says
cannot exist, and it was worse than a refusal because nothing anywhere said it
had happened. The neutral file is removed once it has been translated, because
no harness folder may hold a file that harness does not read.

Three differences between the two shapes, each verified against Claude Code's
own documentation rather than inferred:

  the MCP wrapper   The portable file carries `$schema` and `mcpServers`.
                    Claude Code's carries `mcpServers` alone, so only the
                    server map crosses over. Transports need no translation:
                    Claude Code takes `streamable-http` as an alias for its own
                    `http`, and takes `stdio` and `sse` under those names.

  the path variables Agent Plugins reserves `${PLUGIN_ROOT}` and
                    `${PLUGIN_DATA}` for the client to expand. Claude Code
                    expands `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}`
                    and knows nothing of the shorter pair, which would reach a
                    user as a literal string in a path. Both are renamed
                    everywhere they appear in either translated file.

  the hook events   The neutral vocabulary is the four moments five harnesses
                    have in common. Claude Code names about thirty events, and
                    all four moments land on exactly one each, so nothing here
                    is approximated. A moment with no exact event would be a
                    hook that does not fire, which is a false security claim,
                    and it would be refused rather than mapped to the nearest
                    thing.

What a neutral hook rule is, stated here because this is the first emitter to
read one: a list of blocks, each naming `at`, `run`, and optionally `match`.
`run` is a path to a file inside the plugin, not a shell line, so that Foundry
can check at build time that the hook has something to run. Anything else in a
rule is refused rather than ignored, because an ignored key in a guard is a
guard that does less than it appears to.

The moment is named `at` and not `on` because YAML 1.1 resolves a bare `on` to
the boolean true, and every YAML 1.1 reader does it, so `on: session-start`
parses as a rule keyed `true` rather than as a rule naming a moment. That went
unnoticed for as long as nothing read a rule. A key that means one thing
written and another parsed is not a format, so the key is a word YAML leaves
alone and the old spelling is refused by name below rather than silently
becoming an unknown key.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contract import (
    HOOKS_NAME,
    KINDS,
    MCP_NAME,
    Capability,
    EmitError,
    hook_rules,
    metadata,
    read_json,
    remove,
    write_json,
)

TARGETS = ("claude-code",)

CAPABILITIES = {
    "claude-code": Capability(carries=KINDS, cannot={}),
}

METADATA_DIR = ".claude-plugin"
METADATA_NAME = "plugin.json"

# The two paths Claude Code actually reads, from the plugins reference. Neither
# is the neutral name, and a file at the neutral name is not reported as an
# error by Claude Code, it is simply never opened.
MCP_READS = ".mcp.json"
HOOKS_READS = "hooks/hooks.json"

# The client expands the name on the right and passes the name on the left
# through as text. Applied to every string in both translated files.
PATH_VARIABLES = (
    ("${PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}"),
    ("${PLUGIN_DATA}", "${CLAUDE_PLUGIN_DATA}"),
)

# The four neutral moments, and the one Claude Code event each names. Ordered,
# because this is the order the events are written in and a folder's bytes are
# inside its own `contents` fingerprint.
MOMENTS = {
    "session-start": "SessionStart",
    "before-tool": "PreToolUse",
    "after-tool": "PostToolUse",
    "session-end": "SessionEnd",
}

RULE_KEYS = ("at", "run", "match")

# What YAML 1.1 turns a bare `on` key into. Named here so that a rule written
# the old way is refused by that name instead of being reported as a rule
# holding a key called True, which sends the author looking for a typo.
COERCED = True


def refuse(problem: list[str], fix: list[str]) -> EmitError:
    """What is wrong, then what to do about it. A refusal with no next step is a bug."""
    lines = ["CANNOT SHIP THIS TO CLAUDE-CODE.", ""]
    lines += [f"  {line}" if line else "" for line in problem]
    lines.append("")
    lines += [f"  {line}" if line else "" for line in fix]
    return EmitError("\n".join(lines))


def rename_variables(value: object) -> object:
    """Claude Code's own path variables, everywhere a string appears.

    Walks the whole structure rather than a fixed list of fields, because these
    variables are legal in a command, in any argument, in any environment value
    and in a hook's command line, and a field this misses reaches a user as an
    unexpanded literal inside a path.
    """
    if isinstance(value, str):
        for neutral, theirs in PATH_VARIABLES:
            value = value.replace(neutral, theirs)
        return value
    if isinstance(value, dict):
        return {key: rename_variables(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_variables(item) for item in value]
    return value


# ------------------------------------------------------------------- mcp.json
def translate_mcp(manifest: dict, tree: Path) -> None:
    """The server map, under the name Claude Code opens, with the neutral one gone.

    Only `mcpServers` crosses over. `$schema` names the portable specification
    this file was written against, which is a fact about the source and not
    about the folder Claude Code installs, and Claude Code's format does not
    name it.
    """
    neutral = tree / MCP_NAME
    if not neutral.is_file():
        return

    try:
        payload = read_json(neutral)
    except json.JSONDecodeError as broken:
        raise refuse(
            [
                f"{MCP_NAME} is not valid JSON: {broken}.",
                f"Declared in {manifest['root'] / MCP_NAME}.",
            ],
            ["Fix the file."],
        ) from broken

    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    if not isinstance(servers, dict):
        raise refuse(
            [
                f"{MCP_NAME} has no 'mcpServers' object.",
                f"Declared in {manifest['root'] / MCP_NAME}.",
                "",
                "Claude Code reads that map and nothing else out of this file, so a",
                "plugin without one installs, reports success, and starts no server.",
            ],
            ["Add it. An empty one is fine, a missing one is not."],
        )

    remove(neutral)
    write_json(tree / MCP_READS, {"mcpServers": rename_variables(servers)})


# ----------------------------------------------------------- hooks/hooks.yaml
def check_rule(rule: object, index: int, where: Path, tree: Path) -> None:
    """One neutral rule, against the only three keys a rule has.

    Every fault here is silent at the user's end. Claude Code does not report an
    event name it does not know, or a command that is not there: the hook simply
    never fires, and a hook that never fires is usually a guard somebody is
    relying on.
    """
    named = f"rule {index + 1} of {HOOKS_NAME}"

    if not isinstance(rule, dict):
        raise refuse(
            [f"{named} is not a block.", f"Declared in {where}."],
            ["Write each rule as a block naming 'on' and 'run'."],
        )

    if COERCED in rule:
        raise refuse(
            [
                f"{named} names the moment with 'on'.",
                f"Declared in {where}.",
                "",
                "YAML 1.1 resolves a bare 'on' to the boolean true, so that line does not",
                "reach Foundry as a key called 'on' at all, and the rule it belongs to",
                "names no moment. Every YAML 1.1 reader does this, so quoting it here",
                "would only move the problem to whatever reads the file next.",
            ],
            ["Rename the key to 'at'. The value does not change."],
        )

    unknown = sorted(key for key in rule if key not in RULE_KEYS)
    if unknown:
        listed = ", ".join(repr(key) for key in unknown)
        it = "it" if len(unknown) == 1 else "them"
        raise refuse(
            [
                f"{named} holds {listed}.",
                f"A hook rule names {', '.join(RULE_KEYS)} and nothing else.",
                f"Declared in {where}.",
                "",
                "An unknown key is refused rather than ignored: a guard that quietly",
                "does less than it says is worse than one that does not build.",
            ],
            [f"Take {it} out."],
        )

    moment = rule.get("at")
    if moment not in MOMENTS:
        said = "names no 'at'" if "at" not in rule else f"is set to run at {moment!r}"
        raise refuse(
            [
                f"{named} {said}.",
                f"The moments a hook can name are: {', '.join(MOMENTS)}.",
                f"Declared in {where}.",
                "",
                "Those four are what every harness Foundry emits for has in common.",
                "A moment outside them cannot be written for all of them, and a hook",
                "that does not fire is a guard that is not there.",
            ],
            ["Set 'on' to one of the four."],
        )

    run = rule.get("run")
    if not isinstance(run, str) or not run:
        raise refuse(
            [
                f"{named} names no 'run'.",
                f"Declared in {where}.",
            ],
            ["Add 'run', the path to the file this hook runs."],
        )

    if not (tree / run).is_file():
        raise refuse(
            [
                f"{named} runs {run!r}, which this plugin does not hold.",
                f"Declared in {where}.",
                "",
                "'run' is a path to a file inside the plugin, not a shell line, so that",
                "a hook pointing at nothing is caught here rather than never firing on",
                "somebody else's machine. Put any shell work inside that file.",
            ],
            [
                "Either correct the path, or add the file. If 'exclude' names the",
                "directory it lives in, that is why it is not here.",
            ],
        )

    match = rule.get("match")
    if match is not None and not isinstance(match, str):
        raise refuse(
            [f"{named} has a 'match' that is not a line of text.", f"Declared in {where}."],
            ["Write it as a single pattern, or take the line out."],
        )


def translate_hooks(manifest: dict, tree: Path) -> None:
    """The four moments as Claude Code's own events, with the neutral file gone.

    Only `hooks/hooks.yaml` is removed, never the `hooks/` directory: it is a
    content directory and the scripts the rules run usually live beside it.

    Events are written in the fixed order of MOMENTS and rules keep the order
    the author wrote them, so the same source always produces the same bytes.
    A folder's bytes are inside its own `contents` fingerprint, and a map whose
    order came from a dictionary somewhere would move that number for nobody.
    """
    neutral = tree / HOOKS_NAME
    if not neutral.is_file():
        return

    where = manifest["root"] / HOOKS_NAME
    try:
        rules = hook_rules(tree)
    except Exception as broken:  # yaml raises its own family of errors
        raise refuse(
            [f"{HOOKS_NAME} is not valid YAML: {broken}.", f"Declared in {where}."],
            ["Fix the file."],
        ) from broken

    if not isinstance(rules, list):
        raise refuse(
            [
                f"{HOOKS_NAME} does not hold a list of rules.",
                f"Declared in {where}.",
            ],
            ["Write it as a list, one block per hook, each naming 'on' and 'run'."],
        )

    for index, rule in enumerate(rules):
        check_rule(rule, index, where, tree)

    events: dict[str, list[dict]] = {}
    for moment, event in MOMENTS.items():
        entries = []
        for rule in rules:
            if rule["at"] != moment:
                continue
            entry: dict[str, object] = {}
            if rule.get("match"):
                entry["matcher"] = rule["match"]
            # The variable is quoted and the rest of the path is not, which is
            # the form Claude Code's own documentation uses: it survives an
            # install path with a space in it without quoting the whole line
            # into a single argument.
            entry["hooks"] = [{"type": "command", "command": f'"${{CLAUDE_PLUGIN_ROOT}}"/{rule["run"]}'}]
            entries.append(entry)
        if entries:
            events[event] = entries

    remove(neutral)
    if events:
        write_json(tree / HOOKS_READS, {"hooks": events})


# ------------------------------------------------------------------- emitting
def emit(target: str, manifest: dict, tree: Path) -> None:
    """The manifest Claude Code reads, then the two files it reads instead of the neutral ones."""
    write_json(tree / METADATA_DIR / METADATA_NAME, metadata(manifest))
    translate_mcp(manifest, tree)
    translate_hooks(manifest, tree)
