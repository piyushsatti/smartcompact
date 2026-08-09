#!/usr/bin/env python3
"""The portable Agent Plugins 1.0.0 package, and the Codex folder built on it.

Agent Plugins 1.0.0 was published on 2026-08-06 by a steering committee of
Amazon, Cursor, Microsoft, OpenAI and Vercel, with Google joining. It is the
one package shape more than one vendor agreed to, so Foundry adopts it rather
than inventing a neutral form of its own.

It standardises exactly two component types, skills and MCP servers. Its own
text says commands, hooks, agents, rules and LSP servers remain too
client-specific for a stable portable contract and are outside version 1, so
the portable folder carries none of them and the loss has to be written down.

    plugin.json                     root, not inside a dot directory
    mcp.json                        root, the path the specification names
    skills/<name>/SKILL.md          immediate children only
    foundry.lock.json

Codex is here rather than in a module of its own because it is a client of the
same package: the published compatible-client list gives it skills and MCP over
the stdio and streamable-http transports. It adds one file and takes one
transport away, and both are recorded below.

Everything this module writes was checked against the published schema and the
specification text rather than against the design document, because the
manifest is closed and a client that reads it rejects the whole plugin on any
violation other than an unknown top-level field. Three places where the design
document and the primary sources disagree, all resolved in favour of the
sources:

  author        The schema types `author` as an object with optional name,
                email and url, and the specification says any other field or
                value type makes the manifest invalid. The design document
                shows a plain string. A string is refused here rather than
                wrapped, because guessing which of the three fields the author
                meant is Foundry deciding, and the build never decides.

  repository    The schema carries it and `METADATA_KEYS` in `resolve.py` does
                not, so no manifest can set it and this emitter never writes
                it. Nothing is invented to fill it.

  mcp.json      The specification requires `$schema` and `mcpServers` and
                nothing else at the top level, and requires a `type` on every
                server. The design document's example has neither. A file
                missing `$schema` does not fail loudly: the client disables MCP
                for the whole plugin and carries on, which is the silent
                failure Foundry exists to catch, so it is refused.

Codex differs from the portable package in exactly two ways.

The first is a second manifest. Codex 0.139.0, read from its own binary,
requires `.codex-plugin/plugin.json` and knows nothing of Agent Plugins: the
string `agent-plugins.org` does not appear in it anywhere. So the two manifests
are not a current file and a legacy one, they are the two sides of the release
where Codex adopted the standard, and a folder carrying only one of them is
unreadable on the other side. `.codex-plugin/plugin.json` holds the same fields
without `$schema`, all of which that Codex accepts, and it also names where the
components are. The root manifest is a closed object with nowhere to put a
path, and the Codex that reads the overlay reads nothing else: both of its
component path fields are optional and default to nothing, so a component the
overlay does not point at is one that Codex never looks for. Without the
`mcpServers` line the plugin installs, reports success, and starts no server,
which is the failure this whole module exists to catch. The overlay does not
hold the `interface` block that OpenAI's curated marketplace ingestion asks
for, because a display name, a category and a default prompt are content
Foundry does not have and will not make up.

The second is the `sse` transport. The portable schema permits all three
transports and the compatible-client list gives Codex only stdio and
streamable-http, so an `sse` server reaches a Codex user as a server that is
silently skipped. That is refused here rather than dropped, because it is not
the kind that cannot be carried but one server inside a file that can.

What this folder does not carry, and why it is narrower than the design
document's Codex layout: agents, commands and hooks. The alpha ships hooks on
Claude Code only, Codex's own plugin manifest names no agent or command
location, and no per-harness hook event mapping has been read from source for
any harness. Writing the neutral `hooks/hooks.yaml` into a Codex folder would
leave a file there that nothing reads, and translating it into invented event
names would ship a guard that does not guard. Both are worse than a recorded
drop, so all three are declared as losses and the manifest has to name them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .contract import (
    MCP_NAME,
    METADATA_KEYS,
    Cannot,
    Capability,
    EmitError,
    metadata,
    read_json,
    skill_dirs,
    write_json,
)

TARGETS = ("agent-plugins", "codex")

SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

# The manifest sits at the package root. Every other harness Foundry emits for
# hides its manifest in a dot directory, so this is the easy thing to get
# wrong, and a manifest one level off is a plugin no client finds at all.
MANIFEST_NAME = "plugin.json"

# Codex's own manifest, required by every Codex that predates its adoption of
# the standard.
CODEX_DIR = ".codex-plugin"

CAPABILITIES = {
    "agent-plugins": Capability(
        carries=("skills", "mcp"),
        cannot={
            "agents": Cannot("version 1.0.0 of Agent Plugins defines no agent component"),
            "commands": Cannot("version 1.0.0 of Agent Plugins defines no command component"),
            "hooks": Cannot("version 1.0.0 of Agent Plugins defines no hook component"),
            "allowed-tools": Cannot("no client of the portable package reads allowed-tools"),
        },
    ),
    "codex": Capability(
        carries=("skills", "mcp"),
        cannot={
            "agents": Cannot("a Codex subagent is a configuration layer a plugin cannot carry"),
            "commands": Cannot("Codex retired custom prompts and directs authors to skills"),
            "hooks": Cannot("no Codex hook event vocabulary has been read from source"),
            "allowed-tools": Cannot("Codex does not read allowed-tools"),
        },
    ),
}

# What each target's clients connect with. Agent Plugins permits all three and
# marks `sse` optional for a client; the published compatible-client list gives
# Codex stdio and streamable-http and not the third. A transport a client does
# not have is not an error it reports, it is a server it skips, so the list is
# here and a server outside it is refused.
CONNECTS = {
    "agent-plugins": ("stdio", "streamable-http", "sse"),
    "codex": ("stdio", "streamable-http"),
}

# The harness as a person writes it, for the middle of a sentence. A target
# name is a key in a manifest, and reading 'codex says nothing' in prose looks
# like a typo rather than like the name of a product.
HARNESS = {"agent-plugins": "the portable package", "codex": "Codex"}

# What a YAML value is, in the words someone writing YAML would use. `str` and
# `dict` name Python types, and the person reading this refusal is not writing
# Python.
SHAPE = {
    str: "a line of text",
    list: "a list",
    dict: "a block",
    int: "a number",
    float: "a number",
    bool: "true or false",
}


def shape(value: object) -> str:
    return SHAPE.get(type(value), "not what the schema expects")


# Section 5.5 of the specification, and the same rule as the schema's own
# pattern. Foundry's `id` is the looser of the two: it permits an underscore,
# a leading or trailing dot or hyphen, and any length. Every one of those is a
# manifest a client rejects outright, so the gap is checked here.
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
NAME_MAX = 64

AUTHOR_KEYS = ("name", "email", "url")

MCP_TOP_LEVEL = ("$schema", "mcpServers")

# The three closed server variants of section 7.2.1, each as the fields it
# requires beyond `type` and the fields it permits. A server entry matches
# exactly one of them, and the specification is blunt about what breaks a
# match: an unknown field, an unknown `type` value, or a field belonging to
# another variant. Closed means a field is not ignored, it is fatal to that
# entry, and section 7.2.2 has the client skip the entry and carry on.
VARIANTS = {
    "stdio": (("command",), ("args", "env", "cwd")),
    "streamable-http": (("url",), ("headers",)),
    "sse": (("url",), ("headers",)),
}

# What the field a variant requires is for, in the specification's own words,
# so the line telling the author to add it says what to write there.
FIELD_IS = {
    "command": "the executable to launch",
    "url": "the MCP endpoint URL",
}

# The client supplies both of these itself. A server that sets either one in
# `env` does not override anything, it invalidates the whole entry.
RESERVED_ENV = ("PLUGIN_ROOT", "PLUGIN_DATA")

# Metadata the schema types as a plain string. `keywords` is an array of
# strings and is checked separately; `author` is an object and has its own
# rules. Anything a manifest hands over with the wrong type here is fatal to
# the plugin rather than ignored, so it is worth a sentence rather than a
# stack trace on somebody else's machine.
STRING_FIELDS = tuple(key for key in METADATA_KEYS if key not in ("author", "keywords"))

# The three things a violation costs, written once because they are the whole
# reason any of this is checked here rather than left to the client. None of
# the three raises anything the author or the user ever sees.
FATAL = [
    "A field of the wrong type is fatal rather than ignored: the client rejects",
    "the plugin and loads none of it.",
]
DISABLED = [
    "The client disables MCP for this plugin and loads the rest, so the plugin",
    "installs, reports success, and the server it exists to provide is absent.",
]
SKIPPED = [
    "The client skips that server and loads the rest, so the plugin installs",
    "and reports success without it.",
]


def refuse(target: str, problem: list[str], where: Path, consequence: list[str], fix: list[str]) -> EmitError:
    """Name what is wrong, where it was written, what it costs, and both ways out.

    Every refusal in this module has the same four parts, because the reader is
    someone whose build just stopped and who has no reason to know anything
    about Agent Plugins. The consequence part is the one that is easy to leave
    out and the one that decides whether they fix it or work around it: almost
    every violation here costs the whole plugin rather than the one field, and
    costs it silently.

    `where` names the file in the author's own repository, never the staged
    copy the emitter is actually looking at. A path into a build directory that
    no longer exists by the time the message is read is not a location.
    """
    blocks = [problem, [f"Declared in {where}."], consequence, [*fix, f"Or drop {target} from 'targets'."]]
    lines = [f"CANNOT SHIP THIS TO {target.upper()}.", ""]
    for block in blocks:
        lines += [f"  {line}" if line else "" for line in block]
        lines.append("")
    return EmitError("\n".join(lines).rstrip())


# ------------------------------------------------------------------ the name
def name_fault(name: str) -> str | None:
    """Which of the four name rules this one breaks, or None if it breaks none.

    Reported one rule at a time and in the order the specification lists them,
    so the sentence names a single thing to change. A list of everything wrong
    with a name reads as a specification and sends the author to look one up.
    """
    if not name or len(name) > NAME_MAX:
        return f"a name is 1 to {NAME_MAX} characters and this one is {len(name)}"
    wrong = sorted({character for character in name if not re.fullmatch(r"[a-z0-9.-]", character)})
    if wrong:
        listed = ", ".join(repr(character) for character in wrong)
        return f"only lowercase letters, digits, dots and hyphens are allowed, and this one holds {listed}"
    if not (name[0].isalnum() and name[-1].isalnum()):
        return "a name starts and ends on a letter or a digit"
    if "--" in name:
        return "two hyphens in a row are not allowed"
    if ".." in name:
        return "two dots in a row are not allowed"
    if not NAME_RE.fullmatch(name):
        return "it does not match the name pattern the schema publishes"
    return None


def check_name(target: str, manifest: dict) -> None:
    fault = name_fault(manifest["id"])
    if fault is None:
        return
    raise refuse(
        target,
        [
            "This id is not a name Agent Plugins 1.0.0 allows:",
            "",
            f"    {manifest['id']}",
            "",
            f"{fault[0].upper()}{fault[1:]}.",
        ],
        manifest["manifest_path"],
        [
            "A name that breaks the rule is not a warning. The client rejects the",
            "plugin and loads none of its skills and none of its MCP servers.",
        ],
        ["Either change 'id' to a name that fits, which every other harness", "accepts too."],
    )


# ---------------------------------------------------------------- the author
def check_author(target: str, manifest: dict) -> None:
    """`author` is an object, and the shape is not something to guess at.

    Wrapping a string as {"name": ...} would be Foundry deciding what the
    author meant, on a field that also takes an email and a url. It is one line
    for the person who wrote it and a permanent guess for everyone else, so it
    is refused with the block to write rather than fixed quietly.
    """
    author = manifest.get("author")
    if author is None:
        return
    where = manifest["manifest_path"]

    if not isinstance(author, dict):
        raise refuse(
            target,
            [
                f"'author' is {shape(author)}, and Agent Plugins 1.0.0 declares author a",
                "block with an optional name, email and url.",
            ],
            where,
            FATAL,
            [
                "Write it as a block, which Claude Code reads too:",
                "",
                "    author:",
                "      name: Your Name",
                "",
                "Or take the line out.",
            ],
        )

    unknown = sorted(key for key in author if key not in AUTHOR_KEYS)
    if unknown:
        listed = ", ".join(repr(key) for key in unknown)
        raise refuse(
            target,
            [
                f"'author' holds {listed}, and Agent Plugins 1.0.0 allows an author",
                f"only {', '.join(AUTHOR_KEYS)}.",
            ],
            where,
            ["Any other field makes the manifest invalid, and the client rejects the", "whole plugin."],
            [f"Either take {'it' if len(unknown) == 1 else 'them'} out of the author block."],
        )

    mistyped = sorted(key for key, value in author.items() if not isinstance(value, str))
    if mistyped:
        raise refuse(
            target,
            [f"'author.{mistyped[0]}' is not a string, and every field of an author is a string."],
            where,
            FATAL,
            ["Either quote the value, or take the line out."],
        )


# ------------------------------------------------------- the rest of the fields
def check_fields(target: str, manifest: dict) -> None:
    """Every other metadata field, checked for the type the schema declares.

    These are cheap and they are all fatal. `description` written as a YAML
    list, or `keywords` written as one word rather than a list, costs the whole
    plugin at load and reads as a working manifest right up until then.
    """
    where = manifest["manifest_path"]
    for key in STRING_FIELDS:
        value = manifest.get(key)
        if value is not None and not isinstance(value, str):
            raise refuse(
                target,
                [
                    f"'{key}' is {shape(value)}, and Agent Plugins 1.0.0 declares",
                    f"{key} a string.",
                ],
                where,
                FATAL,
                ["Either write it on one line as text, or take the line out."],
            )

    keywords = manifest.get("keywords")
    if keywords is None:
        return
    if not isinstance(keywords, list) or any(not isinstance(word, str) for word in keywords):
        raise refuse(
            target,
            [
                "'keywords' is not a list of words, and Agent Plugins 1.0.0 declares",
                "keywords an array of strings.",
            ],
            where,
            FATAL,
            ["Write it as a list:", "", "    keywords:", "      - review", "", "Or take the line out."],
        )


# ------------------------------------------------------------------- mcp.json
def check_mcp(target: str, manifest: dict, tree: Path) -> None:
    """The MCP file ships exactly as written, so it is checked exactly as read.

    Every fault below is silent at the user's end. A bad top-level shape makes
    the client disable MCP for the plugin and carry on loading the skills, so
    the plugin installs, reports success, and the server it exists to provide
    is simply not there. A bad server entry is skipped the same way. Nobody
    downstream is told, and the author never sees it, which is precisely the
    failure this build tool exists to move back to the person who can fix it.

    Absent is not a fault: the specification says a missing component location
    is never an error.
    """
    path = tree / MCP_NAME
    if not path.is_file():
        return
    where = manifest["root"] / MCP_NAME

    try:
        payload = read_json(path)
    except json.JSONDecodeError as broken:
        raise refuse(
            target,
            [f"{MCP_NAME} is not valid JSON: {broken}."],
            where,
            DISABLED,
            ["Fix the file."],
        ) from broken

    if not isinstance(payload, dict):
        raise refuse(target, [f"{MCP_NAME} does not hold a JSON object."], where, DISABLED, ["Fix the file."])

    declared = payload.get("$schema")
    if declared != MCP_SCHEMA:
        missing = "$schema" not in payload
        said = "declares no '$schema'." if missing else "declares the wrong '$schema':"
        found = [""] if missing else ["", f"    {declared}", ""]
        raise refuse(
            target,
            [
                f"{MCP_NAME} {said}",
                *found,
                "Agent Plugins 1.0.0 requires exactly this value, and it has to name the",
                "same version as plugin.json does. It says which specification the file",
                "was written against, so it is a fact rather than boilerplate.",
            ],
            where,
            [
                "A version the client does not recognise makes it disable MCP for this",
                "plugin and carry on, so the plugin installs and the server is not there.",
            ],
            ["Make it the first line of the file:", "", f'    "$schema": "{MCP_SCHEMA}",', ""],
        )

    extra = sorted(key for key in payload if key not in MCP_TOP_LEVEL)
    if extra:
        it = "it" if len(extra) == 1 else "them"
        raise refuse(
            target,
            [
                f"{MCP_NAME} holds {', '.join(repr(key) for key in extra)} at the top level.",
                f"Agent Plugins 1.0.0 allows {' and '.join(MCP_TOP_LEVEL)} there and nothing else.",
            ],
            where,
            DISABLED,
            [f"Take {it} out, or move {it} inside a server."],
        )

    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        raise refuse(
            target,
            [f"{MCP_NAME} has no 'mcpServers' object.", "An empty one is fine, a missing one is not."],
            where,
            DISABLED,
            ["Add it."],
        )

    for name in sorted(servers):
        check_server(target, name, servers[name], where)


def check_server(target: str, name: str, server: object, where: Path) -> None:
    """One server entry, against the closed variant its own 'type' names.

    Nothing here reaches anyone downstream on its own. An entry that breaks any
    of these rules is skipped by the client, which loads the other servers and
    the skills and carries on, and reporting the skipped entry is only a SHOULD.
    So the plugin installs, says success, and one of the servers it exists to
    provide is absent, with no line anywhere saying which. Foundry can see at
    build time that the entry loads nowhere, so the refusal belongs here.

    Checked: the transport this folder's clients connect with, the fields the
    variant requires, any field it does not name, and the two environment names
    the client reserves. Not checked yet, and failing the same silent way: what
    is inside each field, from a value's own type through to the URL's form, the
    command's single-token form and where a working directory may point.
    """
    named = f"mcpServers.{name} in {MCP_NAME}"
    if not isinstance(server, dict):
        raise refuse(
            target, [f"{named} is not an object."], where, SKIPPED, ["Give it a configuration object."]
        )

    kind = server.get("type")
    carried = CONNECTS[target]
    if kind is None:
        raise refuse(
            target,
            [
                f"{named} declares no 'type'.",
                "Every server entry names its transport. There is no default, and nothing",
                "is inferred from the other fields.",
            ],
            where,
            SKIPPED,
            [f'Add "type", one of {", ".join(carried)}.'],
        )

    if not isinstance(kind, str) or kind not in VARIANTS:
        # Naming what this folder carries is only worth a line when it is
        # narrower than the specification. Saying both when they are the same
        # reads as a second rule the author has to hold in their head, and
        # there is only one.
        defines = "Agent Plugins 1.0.0 defines stdio, streamable-http and sse"
        narrower = len(carried) < len(CONNECTS["agent-plugins"])
        raise refuse(
            target,
            [
                f"{named} declares type {kind!r}, which is not a transport.",
                f"{defines}, and this" if narrower else f"{defines}.",
                *([f"folder carries {' and '.join(carried)}."] if narrower else []),
            ],
            where,
            SKIPPED,
            ["Correct the type."],
        )

    # `sse` is the one transport a conforming client is allowed to leave out,
    # so a real variant this folder does not carry is always that one.
    if kind not in carried:
        raise refuse(
            target,
            [
                f"{named} uses 'sse', the deprecated HTTP+SSE transport.",
                f"The portable schema permits it, and {HARNESS[target]} does not carry it:",
                f"the published compatible-client list gives it {' and '.join(carried)}",
                "and nothing else.",
            ],
            where,
            [
                "An unsupported transport is skipped, not reported. The plugin installs,",
                f"{HARNESS[target]} says nothing, and that server never connects.",
            ],
            [
                "Either move the server to 'streamable-http', which is the current",
                "transport and what a deprecated 'sse' endpoint usually already serves.",
            ],
        )

    check_entry(target, named, kind, server, where)


def owns(field: str) -> list[str]:
    """Which variants name this field, so a misplaced one is called misplaced.

    A `url` inside a stdio entry is a different mistake from a typo and the
    author fixes it a different way, so the two are not worth one message.
    """
    return [kind for kind, (needs, permits) in VARIANTS.items() if field in (*needs, *permits)]


def check_entry(target: str, named: str, kind: str, server: dict, where: Path) -> None:
    """The fields of one entry, against the one variant its transport selected.

    One fault at a time, in the order someone fixing the file would meet them:
    what is missing, then what does not belong, then the two names inside `env`
    that are the client's to set. A list of everything wrong with an entry reads
    as a specification and sends the author to go and look one up.
    """
    needs, permits = VARIANTS[kind]
    allowed = ("type", *needs, *permits)

    missing = [field for field in needs if field not in server]
    if missing:
        field = missing[0]
        raise refuse(
            target,
            [
                f"{named} declares type {kind!r} and names no {field!r}.",
                f"A {kind} server names {field!r}, {FIELD_IS[field]}.",
            ],
            where,
            SKIPPED,
            [f"Add {field!r}."],
        )

    unknown = sorted(field for field in server if field not in allowed)
    if unknown:
        field = unknown[0]
        elsewhere = owns(field)
        if elsewhere:
            problem = [
                f"{named} declares type {kind!r} and holds {field!r},",
                f"which belongs to a {' or '.join(elsewhere)} server. An entry matches",
                "exactly one of the three closed variants, and a field from another",
                "one makes it match none.",
            ]
            fix = [f"Either take {field!r} out, or change 'type' to {elsewhere[0]!r}."]
        else:
            problem = [
                f"{named} holds {field!r},",
                f"which a {kind} server does not name. It holds {', '.join(allowed)}",
                "and nothing else, and the variants are closed, so a field they do not",
                "name is not ignored.",
            ]
            fix = [f"Take {field!r} out."]
        raise refuse(target, problem, where, SKIPPED, fix)

    env = server.get("env")
    reserved = sorted(key for key in env if key in RESERVED_ENV) if isinstance(env, dict) else []
    if reserved:
        raise refuse(
            target,
            [
                f"{named} sets {reserved[0]} inside 'env'.",
                "The client supplies PLUGIN_ROOT and PLUGIN_DATA itself, and an entry that",
                "names either one is invalid rather than overriding anything.",
            ],
            where,
            SKIPPED,
            [
                f"Take {reserved[0]} out of 'env'. Where a value needs that path, write",
                f"it as ${{{reserved[0]}}} and the client expands it.",
            ],
        )


# ------------------------------------------------------------------- emitting
def manifests_written(target: str) -> tuple[str, ...]:
    """The paths this target's emitter writes, relative to the folder root."""
    if target == "codex":
        return (MANIFEST_NAME, f"{CODEX_DIR}/{MANIFEST_NAME}")
    return (MANIFEST_NAME,)


def refuse_to_overwrite_theirs(target: str, manifest: dict, tree: Path) -> None:
    """A manifest the author wrote is not a file this target may replace.

    Every top-level file ships unless 'exclude' names it, so a plugin repository
    that keeps its own root `plugin.json` has already copied it into the neutral
    tree, inside the fingerprint its own pin names. Writing over it would swap
    what the author wrote for something generated, and keeping it would ship a
    package whose manifest is not the one this target reads. Both are the build
    picking a winner, so it refuses instead.

    Root `plugin.json` is the likeliest collision Foundry has: it is a common
    filename, and this is the one manifest that sits at the package root rather
    than inside a dot directory.
    """
    theirs = [name for name in manifests_written(target) if (tree / name).exists()]
    if not theirs:
        return
    subject = "That name is" if len(theirs) == 1 else "Each name above is"
    raise EmitError(
        f"CANNOT SHIP THIS TO {target.upper()}.\n\n  "
        + "\n  ".join(theirs)
        + f"\n\n  {subject} both a file this plugin already holds and a file this\n"
        "  folder writes. Overwriting yours would swap what you wrote for a\n"
        "  generated manifest, and keeping yours would ship a package whose\n"
        f"  manifest is not the one {target} reads.\n\n"
        "  Every top-level file ships unless 'exclude' names it.\n\n"
        f"  Declared by {manifest['manifest_path']}.\n\n"
        "  Either add each name above to 'exclude', so it stays a file of this\n"
        f"  repository and ships nowhere, or drop {target} from 'targets'."
    )


def codex_paths(tree: Path) -> dict:
    """Where the components are, which only Codex's own manifest can say.

    The root manifest is a closed object of ten metadata fields with nowhere to
    put a path, because a client of the standard already knows the two paths the
    standard fixes. Codex 0.139.0 does not: it reads `.codex-plugin/plugin.json`
    alone, and that manifest's skills and mcpServers fields are each an optional
    string that defaults to nothing. A component the overlay does not name is
    one that Codex never looks for, so an `mcp.json` shipped without this line
    sits in the installed folder unread while the install reports success.

    Each path is named only when the thing is actually in the folder. A manifest
    pointing at a directory the package does not hold is the same failure in the
    other direction, and it is the emitter's own file to get right.

    A Codex new enough to read the root manifest takes only its own paths for
    apps and hooks and its interface block from here, so both lines are ignored
    there rather than fought over.
    """
    paths = {}
    if skill_dirs(tree):
        paths["skills"] = "./skills"
    if (tree / MCP_NAME).is_file():
        paths["mcpServers"] = f"./{MCP_NAME}"
    return paths


def emit(target: str, manifest: dict, tree: Path) -> None:
    """The manifest at the root, and for Codex the second one beside it.

    Everything is checked before anything is written, so a folder never appears
    half-conformant. There is nothing to translate: the neutral tree already
    holds `skills/` and `mcp.json` at the paths this specification names, which
    is the whole reason Foundry adopted it as the source form.
    """
    check_name(target, manifest)
    check_author(target, manifest)
    check_fields(target, manifest)
    check_mcp(target, manifest, tree)
    refuse_to_overwrite_theirs(target, manifest, tree)

    described = metadata(manifest)
    write_json(tree / MANIFEST_NAME, {"$schema": SCHEMA, **described})

    if target == "codex":
        # The same fields without `$schema`, plus where each component is.
        # Every one of them is in the set of keys Codex's own plugin validation
        # accepts, and `$schema` is not: a Codex reading this file predates the
        # standard and would report the key as one it does not accept.
        write_json(tree / CODEX_DIR / MANIFEST_NAME, {**described, **codex_paths(tree)})
