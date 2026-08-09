#!/usr/bin/env python3
"""OpenCode and Pi, the two harnesses with no package format to target.

Neither has an install command, a version, or an update path for a plugin, so
what they get is a tree of loose files that a person copies into a
configuration directory by hand. That is a real difference from a package and
the plugin's own README has to say so rather than claim support. Nothing here
writes a manifest, and the version number survives only in `foundry.lock.json`
and in the release asset name.

Both folders are the neutral tree with the unreadable kinds already taken out,
because the neutral directory names are the names both harnesses read. Copy an
OpenCode folder's contents into `.opencode/` and copy a Pi folder's contents
into `.pi/`, and every file lands where that harness looks for it.

    opencode                        pi
      skills/<name>/SKILL.md          skills/<name>/SKILL.md
      agents/<name>.md                prompts/<name>.md
      foundry.lock.json               foundry.lock.json

The one translation is Pi's. Pi calls a user-invocable prompt unit a prompt
template, loads it from `prompts/*.md`, and reads `argument-hint` where the
neutral form writes `arguments`. So `commands/` is rewritten into `prompts/`
and the neutral directory is removed, because a folder that holds a directory
its harness never reads ships a file the record cannot explain.

Four capabilities here disagree with the design document, the first three with
its section 2 folder listings and the fourth with its section 3 loss table, and
each disagreement was settled against that harness's own documentation:

  OpenCode reads MCP servers from an `mcp` block inside the user's own
  `opencode.json`, whose shape is not the `mcpServers` shape in the neutral
  `mcp.json`. No file a shipped folder can carry reaches it, so copying
  `mcp.json` in would put a file in the folder that nothing reads.

  Pi has no agent surface. Its packages carry skills, prompt templates, themes
  and extensions, and an extension is a TypeScript module rather than anything
  Foundry can generate from a markdown agent.

  Pi calls its command surface prompt templates and reads `prompts/`, not
  `commands/`, so shipping the neutral directory name would put every command
  somewhere Pi never looks.

  Pi carries `allowed-tools`, where the design drops it on every target except
  Claude Code. Pi's own skill documentation lists the field in the SKILL.md
  frontmatter it accepts, as a space-delimited list of pre-approved tools,
  marked experimental. So the design's reason for dropping it, that Pi does not
  state it enforces the field and shipping one would read as a boundary that is
  not there, is untrue twice over: Pi documents reading it, and pre-approval
  widens what a skill may do rather than fencing it, so removing the field
  narrows the skill instead of removing a false boundary.

Skills are the one kind both harnesses carry, and the two do not agree on what
counts as one. OpenCode reads `skills/<name>/SKILL.md` and nothing else, while
Pi reads that and also discovers a loose `.md` file sitting directly beside
those directories, so a folder holding a loose file exposes a skill on Pi and
nothing on OpenCode. That is the difference-by-harness the whole design exists
to make impossible, and the build-wide depth check cannot catch it because it
looks for `SKILL.md` files and a shape holding none produces nothing to look
at, so a stray shape under `skills/` is refused here for both harnesses.

OpenCode does publish a command format of its own, which the design document
says it does not. It is left uncarried anyway: OpenCode's own documentation
calls the `template` frontmatter key required on one line and says the markdown
body becomes the template on the next, and emitting a file that a harness might
reject is worse than declaring the gap and printing it. That gap is stated as
Foundry not emitting the format rather than as OpenCode not having one, because
an error message that says something untrue about a harness is a bug in the
same way a silent drop is.

Every capability below was read from documentation rather than from loader
source. Foundry's rule is that code beats prose, so read the loaders before
this ships and expect at least the OpenCode command line to move.
"""

from __future__ import annotations

from pathlib import Path

from .contract import SKILL_NAME, Cannot, Capability, EmitError, remove

TARGETS = ("opencode", "pi")

CAPABILITIES = {
    "opencode": Capability(
        carries=("skills", "agents"),
        cannot={
            "commands": Cannot("Foundry does not emit OpenCode's own command format"),
            "hooks": Cannot("OpenCode has no declarative hook surface"),
            "mcp": Cannot(
                "OpenCode reads MCP servers from the user's own opencode.json, "
                "which no shipped folder can write"
            ),
            "allowed-tools": Cannot("OpenCode does not read allowed-tools"),
        },
    ),
    "pi": Capability(
        carries=("skills", "commands", "allowed-tools"),
        cannot={
            "agents": Cannot(
                "Pi has no agent surface: its packages carry skills, prompt templates, themes and extensions"
            ),
            "hooks": Cannot("Pi has no declarative hook surface"),
            "mcp": Cannot("Pi has no MCP surface"),
        },
    ),
}

# What each harness does with a shape under `skills/` that is not
# `<name>/SKILL.md`. The two answers differ, and the difference is the reason a
# stray shape is refused for both rather than dropped for one.
STRAY_SKILL_LANDS = {
    "opencode": (
        "OpenCode loads a skill from .opencode/skills/<name>/SKILL.md and looks\n"
        "  nowhere else, so each of the above would ship and never be loaded, with\n"
        "  no error anywhere for anyone to read."
    ),
    "pi": (
        "Pi loads a skill from .pi/skills/<name>/SKILL.md, and is the one harness\n"
        "  here that also discovers a loose .md file sitting directly beside those\n"
        "  directories. So each of the above either ships and is never loaded, or,\n"
        "  being a loose .md file, is loaded on Pi and on nothing that reads only\n"
        "  skills/<name>/SKILL.md. Neither outcome is reported anywhere."
    ),
}

# Pi's name for the directory it loads a user-invocable prompt unit from, and
# its name for the hint the neutral form calls `arguments`.
PROMPTS_DIR = "prompts"
ARGUMENTS = "arguments"
ARGUMENT_HINT = "argument-hint"


# ------------------------------------------------------ refusals about content
def check_every_skill_is_a_directory_holding_a_skill_file(
    target: str, tree: Path, manifest_path: Path, lands: str
) -> None:
    """A skill is `skills/<name>/SKILL.md`, and anything else under `skills/` stops.

    Skills are the one kind both harnesses carry, so this is the one place a
    stray shape reaches both, and the two harnesses do not answer it the same
    way. A loose `skills/<name>.md` is discovered on Pi and invisible on
    OpenCode, which means one built folder holding one file would expose two
    different skill lists and nothing anywhere would say so. That is exactly the
    failure the one-level rule exists to foreclose, and a drop cannot express it
    because the folder is not diminished on Pi at all.

    The build-wide depth check does not reach this. It globs for `SKILL.md` and
    reports one nested too deep, so a directory holding no `SKILL.md` anywhere
    produces no match and passes, and a loose markdown file is not a match to
    begin with. What is checked there is where a skill file sits; what is
    checked here is whether a thing is a skill at all.

    `lands` is the whole sentence naming what that harness does with a stray
    shape. It is a parameter rather than one shared line because the two
    harnesses genuinely differ, and an error message that says something untrue
    about a harness is a bug in the same way a silent drop is.

    A dot file is not a skill. An empty content directory kept alive by a
    placeholder is an empty directory, and refusing over one would make the
    Foundry template unbuildable on the day it is copied.
    """
    skills = tree / "skills"
    if not skills.is_dir():
        return
    stray = sorted(
        f"skills/{entry.name}"
        for entry in skills.iterdir()
        if not entry.name.startswith(".") and not (entry / SKILL_NAME).is_file()
    )
    if not stray:
        return
    raise EmitError(
        f"CANNOT SHIP THIS TO {target.upper()}.\n\n  "
        + "\n  ".join(stray)
        + f"\n\n  Declared in {manifest_path}.\n\n"
        f"  A skill is a directory holding a {SKILL_NAME}, and none of the above is one.\n"
        f"  {lands}\n\n"
        f"  Either make each one skills/<name>/{SKILL_NAME}, or take {target} out of\n"
        f"  'targets'."
    )


def check_every_item_is_one_markdown_file(
    target: str, kind: str, tree: Path, manifest_path: Path, reads: str
) -> None:
    """Both harnesses glob one directory for `*.md` and look no further.

    A grouping directory under `agents/` or `commands/`, or a supporting file
    that is not markdown, therefore ships intact and is never loaded, with no
    error raised anywhere: the author sees a folder that looks right and the
    user sees nothing. This is the same failure as a nested skill, which the
    build already refuses for every harness, and it is refused here rather than
    there because which shapes load is a fact about one harness and not about
    the kind.

    A dot file is not an item. An empty content directory kept alive by a
    placeholder is an empty directory, and refusing over one would make the
    Foundry template unbuildable on the day it is copied.
    """
    directory = tree / kind
    if not directory.is_dir():
        return
    stray = sorted(
        f"{kind}/{entry.name}"
        for entry in directory.iterdir()
        if not entry.name.startswith(".") and not (entry.is_file() and entry.suffix == ".md")
    )
    if not stray:
        return
    raise EmitError(
        f"CANNOT SHIP THIS TO {target.upper()}.\n\n  "
        + "\n  ".join(stray)
        + f"\n\n  Declared in {manifest_path}.\n\n"
        f"  {reads} and looks nowhere else.\n"
        f"  Each of the above would ship and never be loaded, with no error anywhere\n"
        f"  for anyone to read.\n\n"
        f"  Either make each one a single markdown file directly under {kind}/, or\n"
        f"  take {target} out of 'targets'."
    )


def check_prompts_is_free(tree: Path, manifest_path: Path) -> None:
    """Nothing may already sit where a command is about to be written.

    A plugin repository holding its own top-level `prompts/` is unusual and
    perfectly legal: it is not a content kind, so nothing upstream looks at it.
    Writing a command over what is already at that path would mean two things
    claimed one name and nobody found out which one shipped, which is the
    collision the build already refuses between two dependencies.
    """
    commands = tree / "commands"
    prompts = tree / PROMPTS_DIR
    if not commands.is_dir() or not prompts.exists():
        return
    if not prompts.is_dir():
        taken = [PROMPTS_DIR]
    else:
        taken = sorted(
            f"{PROMPTS_DIR}/{path.name}" for path in commands.glob("*.md") if (prompts / path.name).exists()
        )
    if not taken:
        return
    raise EmitError(
        "CANNOT SHIP THIS TO PI.\n\n  " + "\n  ".join(taken) + f"\n\n  Declared in {manifest_path}.\n\n"
        f"  Pi loads a prompt template from .pi/prompts/<name>.md, so every command\n"
        f"  this plugin holds has to be written into {PROMPTS_DIR}/, and this plugin already\n"
        f"  fills the paths listed above. Writing over one silently would mean nobody\n"
        f"  finds out which of the two shipped.\n\n"
        f"  Either rename the command or rename what is already there, or take pi out\n"
        f"  of 'targets'."
    )


# ------------------------------------------------------------ the translations
def with_argument_hint(text: str) -> str:
    """Rename `arguments` to `argument-hint`, which is the key Pi reads.

    Rewritten one line at a time rather than by reloading and re-dumping the
    frontmatter, because a re-dump reformats a file the author wrote and every
    reformatted byte lands in the folder's `contents` fingerprint looking like
    a change to the content. A file with no `arguments` line comes back exactly
    as it went in.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        return text
    for index in range(1, closing):
        line = lines[index]
        if line.startswith((" ", "\t")) or line.split(":")[0].strip() != ARGUMENTS:
            continue
        lines[index] = ARGUMENT_HINT + line[len(ARGUMENTS) :]
        break
    return "".join(lines)


def as_prompt_templates(tree: Path) -> None:
    """`commands/<name>.md` becomes `prompts/<name>.md`, the only shape Pi loads.

    The neutral directory goes afterwards. Leaving it would put a directory in
    the folder that Pi never reads, inside the folder's `contents` fingerprint
    with nothing to explain why it is there, which is the leak this whole design
    exists to stop happening again.
    """
    commands = tree / "commands"
    if not commands.is_dir():
        return
    written = sorted(commands.glob("*.md"))
    # An empty content directory kept alive by a placeholder must not leave an
    # empty `prompts/` behind. A directory Pi has no reason to read is still a
    # thing in the folder that the record cannot explain.
    if written:
        prompts = tree / PROMPTS_DIR
        prompts.mkdir(exist_ok=True)
        for path in written:
            (prompts / path.name).write_text(with_argument_hint(path.read_text()))
    remove(commands)


# ------------------------------------------------------------------- emitting
def emit(target: str, manifest: dict, tree: Path) -> None:
    """One folder of loose files, in the shape that harness reads them.

    Everything either harness cannot carry is already gone by the time this
    runs, so what is left is the question of whether what remains sits where
    that harness looks.

    Skills come first because they are the kind both harnesses carry, so the
    shape check is the same one for both and only the sentence explaining the
    consequence differs.
    """
    manifest_path = manifest["manifest_path"]
    check_every_skill_is_a_directory_holding_a_skill_file(
        target, tree, manifest_path, STRAY_SKILL_LANDS[target]
    )
    if target == "opencode":
        check_every_item_is_one_markdown_file(
            "opencode",
            "agents",
            tree,
            manifest_path,
            "OpenCode loads an agent from .opencode/agents/<name>.md",
        )
        return

    check_every_item_is_one_markdown_file(
        "pi",
        "commands",
        tree,
        manifest_path,
        "Pi loads a prompt template from .pi/prompts/<name>.md",
    )
    check_prompts_is_free(tree, manifest_path)
    as_prompt_templates(tree)
