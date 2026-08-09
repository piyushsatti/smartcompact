#!/usr/bin/env python3
"""The portable manifest, against the schema its publisher serves today.

Agent Plugins 1.0.0 closes its manifest with `additionalProperties: false` and
requires `$schema` and `name`, so a client rejects the whole plugin on a single
violation and loads none of its skills and none of its MCP servers. Nothing
warns anybody. That makes this the one target Foundry can be wrong about
silently and completely, and it is also the one target with a published schema,
so it is the one that gets checked against the publisher rather than against
Foundry's own idea of the format.

The schema is fetched rather than vendored. Agent Plugins 1.0.0 was three days
old when this was written, its steering committee is not a foundation, and
Codex hard-fails on any schema version other than 1.0.0 without falling back to
a sibling manifest. A revision therefore strands the package, and a copy of the
schema kept in this repository would keep agreeing with itself while the real
one moved. If the fetch fails this job fails: red means the manifest is
unproven, which is what it is.

**No JSON Schema library is installed, here or anywhere.** `scripts/` may not
import one, because the build runs in strangers' CI and every dependency is a
new way for someone else's build to fail. Adding one to this workflow alone
would be a dependency Foundry's own release then rests on, so the keywords the
fetched schema actually uses are implemented below instead: type, properties,
required, additionalProperties, const, enum, pattern, minLength, maxLength and
items. That is a checker for one small schema, not a JSON Schema implementation,
and the difference is dangerous in exactly one way: a schema revision using a
keyword this file does not implement would be checked as if the keyword were
not there, and the job would pass having proved less than it says. So every
keyword in the fetched document is read first and an unimplemented one stops
the job. Under-checking is loud or it is not a check.

Also checked here, because it is the same file in the same folder: Codex's own
manifest carries no `$schema`. The Codex that reads `.codex-plugin/plugin.json`
predates the standard and reports the key as one it does not accept, so the two
manifests differ on purpose and a build that made them identical would break
the older side while looking tidier.

Operate:
    python3 .github/checks/conformance.py BUILT_DIR PLUGIN_DIR
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harnesses import HARNESS  # noqa: E402
from report import Report  # noqa: E402

SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

# The dialect the fetched document is written in. A different one means the
# keywords below may not mean what this file assumes they mean.
DIALECT = "https://json-schema.org/draft/2020-12/schema"

MANIFEST_NAME = "plugin.json"
CODEX_MANIFEST = Path(".codex-plugin") / MANIFEST_NAME
PLUGIN_MANIFEST = "foundry.plugin.yaml"

ATTEMPTS = 3
PAUSE = 5

# Keywords that say nothing about whether a document is valid.
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "examples", "default"}

# Keywords `check` below implements. Anything else in the fetched schema stops
# the job rather than being passed over.
IMPLEMENTED = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "const",
    "enum",
    "pattern",
    "minLength",
    "maxLength",
    "items",
    "minItems",
    "maxItems",
}

# Keywords whose value is itself a schema, so the walk has to go through them.
SUBSCHEMA = ("items", "additionalProperties")

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


# ------------------------------------------------------------------ the schema
def fetch(url: str) -> dict:
    """The published schema, or a failure that says the network is the reason.

    A fetch that failed and a manifest that does not conform are two different
    facts and they get two different messages. Reading one as the other sends
    somebody to go and change an emitter that is fine.
    """
    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as problem:
            last = str(problem)
            if attempt < ATTEMPTS:
                time.sleep(PAUSE)
    sys.exit(
        f"could not fetch {url} after {ATTEMPTS} attempts: {last}\n\n"
        "  Nothing about the manifest was proved either way, which is why this is a\n"
        "  failure rather than a pass. The schema is fetched instead of kept here so\n"
        "  that a revision by its publisher is found by Foundry rather than by\n"
        "  somebody whose plugin stopped loading.\n\n"
        "  Either re-run once the site is reachable, or, if the schema moved, follow\n"
        "  it: a new schema version is a Foundry second-number bump, not a patch."
    )


def keywords(schema: dict, seen: set[str]) -> set[str]:
    """Every keyword the fetched document uses, at every depth.

    The walk has to know structure. Keys under `properties` are property names
    and not keywords, so reading them as keywords would report `$schema` and
    `name` as things this file cannot check.
    """
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            for subschema in value.values():
                if isinstance(subschema, dict):
                    keywords(subschema, seen)
            seen.add(key)
        elif key in SUBSCHEMA and isinstance(value, dict):
            keywords(value, seen)
            seen.add(key)
        else:
            seen.add(key)
    return seen


def check_the_checker(schema: dict) -> None:
    """This file is honest about one schema, so it proves that is the schema."""
    if schema.get("$id") != SCHEMA_URL:
        sys.exit(
            f"the document at {SCHEMA_URL} calls itself {schema.get('$id')!r}.\n"
            "  Something answered for that URL other than the plugin manifest schema,\n"
            "  so nothing was checked. Look at what the URL serves now."
        )
    if schema.get("$schema") != DIALECT:
        sys.exit(
            f"the schema is written in {schema.get('$schema')!r} and this checker reads {DIALECT}.\n"
            "  The keywords may no longer mean what it assumes they mean.\n\n"
            "  Read the new dialect before trusting anything here again."
        )
    unknown = sorted(keywords(schema, set()) - IMPLEMENTED - ANNOTATIONS)
    if unknown:
        sys.exit(
            f"the published schema now uses {', '.join(unknown)}, which this checker "
            "does not implement.\n\n"
            "  Passing over a keyword would mean this job reports a conforming manifest\n"
            "  while checking less than it claims, so it stops instead.\n\n"
            "  Either implement each keyword in .github/checks/conformance.py, or, if the\n"
            "  schema moved to a new version, follow it: a new version is a Foundry\n"
            "  second-number bump."
        )


# -------------------------------------------------------------- the validation
def check(value: object, schema: dict, path: str, report: Report) -> None:
    """One value against one subschema, collecting every problem it has.

    Every keyword applies only to the type it is about, which is what the
    specification says and what stops `minLength` reporting on an object. The
    whole document is walked rather than stopped at the first fault, because
    the reader is fixing an emitter and wants the list.
    """
    kind = schema.get("type")
    if kind and not isinstance(value, TYPES[kind]):
        report.wrong(f"{path} is {type(value).__name__} and the schema declares {kind}.")
        return
    if kind == "integer" and isinstance(value, bool):
        report.wrong(f"{path} is a boolean and the schema declares integer.")
        return

    if "const" in schema and value != schema["const"]:
        report.wrong(f"{path} is {value!r} and the schema fixes it at {schema['const']!r}.")
    if "enum" in schema and value not in schema["enum"]:
        report.wrong(f"{path} is {value!r} and the schema allows only {schema['enum']!r}.")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            report.wrong(f"{path} is {value!r} and does not match {schema['pattern']}.")
        if "minLength" in schema and len(value) < schema["minLength"]:
            report.wrong(
                f"{path} is {len(value)} characters and the schema wants at least {schema['minLength']}."
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            report.wrong(
                f"{path} is {len(value)} characters and the schema allows at most {schema['maxLength']}."
            )

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            report.wrong(f"{path} holds {len(value)} and the schema wants at least {schema['minItems']}.")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            report.wrong(f"{path} holds {len(value)} and the schema allows at most {schema['maxItems']}.")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                check(item, schema["items"], f"{path}[{index}]", report)

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                report.wrong(f"{path} names no {name!r}, and the schema requires it.")
        for name, item in value.items():
            here = f"{path}.{name}" if path else name
            if name in properties:
                check(item, properties[name], here, report)
                continue
            extra = schema.get("additionalProperties")
            if extra is False:
                report.wrong(
                    f"{here} is not a field the schema names, and the object is closed. "
                    "An unknown field is not ignored: the client rejects the plugin and "
                    "loads none of it."
                )
            elif isinstance(extra, dict):
                check(item, extra, here, report)


# ------------------------------------------------------------- what is checked
def portable_targets(built: Path, targets: list[str]) -> dict[str, Path]:
    """Every folder that carries the root manifest, whichever harness it is for.

    Codex reads the same package as the portable one, so its folder carries the
    same root manifest and gets the same check. Naming the harnesses here rather
    than only checking agent-plugins is what stops a second folder shipping an
    invalid copy of a file that was checked once somewhere else.
    """
    single = len(targets) == 1
    return {
        target: (built if single else built / target)
        for target in targets
        if MANIFEST_NAME in HARNESS[target].holds
    }


def check_codex_overlay(folder: Path, report: Report) -> None:
    """Codex's own manifest parses and carries no `$schema`.

    The two manifests in a Codex folder are the two sides of the release where
    Codex adopted the standard. The older side reads this file alone and reports
    a key it does not accept, so making the two identical would break it while
    looking like tidying.
    """
    path = folder / CODEX_MANIFEST
    if not path.is_file():
        report.wrong(
            f"{CODEX_MANIFEST} is missing, and the Codex that predates the standard reads only that."
        )
        return
    try:
        overlay = json.loads(path.read_text())
    except json.JSONDecodeError as broken:
        report.wrong(f"{CODEX_MANIFEST} is not valid JSON: {broken}.")
        return
    if "$schema" in overlay:
        report.wrong(
            f"{CODEX_MANIFEST} carries '$schema'. The Codex that reads this file predates "
            "the standard and reports the key as one it does not accept."
        )


def main() -> int:
    built = Path(sys.argv[1]).resolve()
    plugin = Path(sys.argv[2]).resolve()
    source = yaml.safe_load((plugin / PLUGIN_MANIFEST).read_text()) or {}
    targets = [str(name).strip() for name in (source.get("targets") or ["claude-code"])]

    folders = portable_targets(built, targets)
    if not folders:
        sys.exit(
            f"{plugin / PLUGIN_MANIFEST} names no harness that carries a root {MANIFEST_NAME}, "
            f"so there is no portable manifest to check.\n"
            f"  'targets' says: {', '.join(targets)}.\n\n"
            "  Either put agent-plugins back in 'targets', or take this job out of\n"
            "  .github/workflows/ci.yml. A job that quietly checks nothing is worse than\n"
            "  no job, because the badge still says the package conforms."
        )

    schema = fetch(SCHEMA_URL)
    check_the_checker(schema)

    report = Report()
    for target, folder in sorted(folders.items()):
        path = folder / MANIFEST_NAME
        if not path.is_file():
            report.wrong(f"{target}: no {MANIFEST_NAME} at the folder root, where the specification puts it.")
            continue
        try:
            manifest = json.loads(path.read_text())
        except json.JSONDecodeError as broken:
            report.wrong(f"{target}: {MANIFEST_NAME} is not valid JSON: {broken}.")
            continue

        check(manifest, schema, target, report)
        if manifest.get("version") != str(source.get("version")):
            report.wrong(
                f"{target}: {MANIFEST_NAME} says version {manifest.get('version')!r} and "
                f"{PLUGIN_MANIFEST} says {source.get('version')!r}. A folder nobody can trace "
                "back to a source version is a folder nobody can pin."
            )
        if target == "codex":
            check_codex_overlay(folder, report)

    report.finish(f"the manifest in {', '.join(sorted(folders))} conforms to {SCHEMA_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
