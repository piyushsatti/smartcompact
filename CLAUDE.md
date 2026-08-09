# foundry

Foundry is a standalone base. It holds the tooling that turns a plugin repository into a shippable
folder for each agent harness that plugin asked for, and the template a new plugin repository starts
from. Nothing else.

No plugins live here. No skills, agents, shared library, MCP servers or web app live here. All of
that left the repo in the split and now sits in a holding folder outside it. Where each piece lands
is a later session's decision and is not this repo's concern.

## The test for whether something belongs here

**Would someone building a completely unrelated plugin need this? If no, it is not Foundry.**

| Belongs | Does not belong |
|---|---|
| The build tool and the resolver | Any actual plugin, skill, agent or command |
| The manifest format the build tool reads | A library one plugin happens to import |
| The template a plugin repository starts from | Anything specific to Pi's own plugins |
| Conventions and checks that define a valid plugin | Anything that names a particular consumer |
| Foundry's own version and release process | A list of who uses Foundry |

If two parties want to share code between their plugins, they make their own repository and point
at it. Foundry has no opinion and no involvement.

## Layout

| Path | Holds |
|---|---|
| `scripts/resolve.py` | Reads a plugin's manifest, walks its dependencies, settles which Foundry version applies and fingerprints everything. Runs inside a plugin repository, not inside Foundry |
| `scripts/build.py` | Copies the plugin's own content, copies what it takes from each dependency, catches collisions, checks `provides`. Then hands that staged tree to one emitter per harness named in `targets` and writes `foundry.lock.json` inside each folder. Knows nothing about any harness itself |
| `scripts/emitters/__init__.py` | The registry of which module emits which harness, the loss policy, the pruning that takes out every kind a harness cannot read, and the skill depth check. Everything about loss lives here and in no emitter |
| `scripts/emitters/contract.py` | What every emitter module declares, and the file helpers every emitter shares: `write_json`, `metadata`, `skill_dirs`, `frontmatter`, `mcp_servers`, `hook_rules`, `remove`, `read_json` |
| `scripts/emitters/<harness>.py` | One harness's folder, and nothing else. `claude_code.py`, `agent_plugins.py` which also serves Codex, `skills_tree.py` which serves OpenCode and Pi, `instructions.py` |
| `template/` | The starting shape of a plugin repository: manifest, empty content directories, CI workflow, its own README and CLAUDE.md |
| `template/scripts/foundry.py` | The bootstrap stub. The one file genuinely copied into a plugin repo rather than fetched |
| `VERSION` | Foundry's own version, currently 0.1.0 |
| `ruff.toml` | The lint and format gate, pinned so it means the same thing on any machine. Development tooling only: nothing under `scripts/` imports it |
| `tests/` | Fixture plumbing in `repos.py` that writes throwaway plugin repos, plus the rule tests under `tests/scripts/`. Run with `python3 -m unittest discover -s tests` |
| `docs/adr/` | The decisions. `0002-foundry-as-template-and-dependency.md` says what Foundry is; `0003-multi-harness-emitters.md` says what it emits. Both current. `0001` is superseded history |
| `.github/workflows/` | Foundry's own CI. Currently stale, see below |

## Invariants, and what breaking each one costs

| Invariant | Cost of breaking it |
|---|---|
| The bootstrap stub stays tiny and almost never changes | It is the only file that ever needs re-copying by hand across every plugin repository. Anything that might need fixing later belongs in `scripts/`, where one fix reaches everyone |
| Nothing resolves on a user's machine | The whole conflict-free property comes from a plugin arriving as one finished folder. Any feature that makes an installed plugin fetch, resolve or assemble something destroys it |
| The build never picks a winner | Every ambiguity stops the build and names both sides. Choosing silently means nobody finds out a substitution happened |
| There is no silent drop | A declared kind a harness cannot represent stops the build, naming the kind, the harness, the manifest line and both ways forward. Or the author wrote that loss down under `degrade.<harness>.drop`, and then it is printed at build time, recorded in that folder's `foundry.lock.json`, and recorded again in `foundry.release.json`. There is no third outcome. This is the winner rule applied to harnesses: a diminished folder is always a line somebody wrote, never something the tool concluded |
| A Claude Code folder moves only on purpose, with a before-and-after diff run first | Every `contents` fingerprint already sitting in a shipped lock file was measured on those bytes, and every pin written against one stops matching the moment they move, silently, on somebody else's machine. `emitters/claude_code.py` still writes the manifest exactly as the old `write_metadata` did: same `METADATA_KEYS` tuple, same order, same path. A manifest that names no `targets` still gets a lock file with no `target` and no `dropped` field, because a lock file is part of the folder that ships. The folder has moved twice, both before `v0.1.0` and both with the before-and-after listing read. Once when `mcp.json` and `hooks/hooks.yaml` started being translated rather than shipped unread, which moved it only for plugins declaring an MCP server or a hook. Once when a `.gitkeep` at the top of a content directory stopped shipping, which moved it only for plugins carrying one |
| A capability answers for every kind | `carries` and `cannot` in one `Capability` together name all six kinds in `KINDS`, and the framework refuses to dispatch otherwise, calling it a Foundry defect. When a seventh kind is added, no harness can carry it silently on the grounds that nobody re-read that module |
| No harness folder holds a file that harness does not read | An unread file sits outside whatever that harness validates and inside the folder's `contents` fingerprint, so it ships and the record cannot explain why it is there. This is the same failure as the author's local `.claude` settings reaching people who installed a plugin. An emitter that translates a neutral file removes the neutral one as the last step of the translation, and `drop_placeholders` in `build.py` sweeps a dot file out of the top of each content directory before any emitter runs, dropping the directory if that leaves it empty |
| Error messages are the product | Each refusal states what is wrong, where it was declared, and what to do about it. A refusal with no next step is a bug |
| Foundry keeps no list of consumers and never reaches into another repository | The dependency direction only runs one way. A list here inverts it |
| Only pyyaml beyond the standard library | The build tool runs in strangers' CI. Every added dependency is a new way for someone else's build to fail |
| What gets skipped during fingerprinting is frozen | `SKIP_DIRS`, `SKIP_SUFFIXES` and `SKIP_NAMES` in `resolve.py` alone decide what a fingerprint covers, both the pin and the lock file's `contents`. Changing any of the three changes every fingerprint, which invalidates every pin anyone has written. A test asserts all three lists by hand for exactly this reason, and it is what caught `.foundry` being added rather than letting it through. `NEVER_SHIP` in `build.py` is a separate list deciding only what gets copied, and changing it moves no fingerprint at all |
| Nothing skipped by `resolve.py` may be missing from `NEVER_SHIP` | A path outside the fingerprint that still gets copied ships without the lock file's `contents` changing, so the record cannot show it happened. That is how `.claude`, the author's local settings, was reaching people who installed a plugin, and how `.foundry`, the cache the bootstrap stub writes, was putting 170 files of Foundry's own source inside every shipped folder |
| A build never reads its own output or its own scratch | `--out dist` puts both inside the plugin being read. The staging directory is created beside the destination, so copying the plugin root copies the staging directory into itself until the path is too long for the filesystem, and that fails on the first build rather than the second. `copy_own_content` is handed both paths and matches them resolved, because `dist` is a convention in a README and the flag takes anything |
| A pin names the fingerprint of the dependency's source checkout | `resolve()` fingerprints each manifest's `root` and `check_pins` compares every pin against that. The lock file's `contents` is a separate record of what shipped and no pin is ever checked against it. State it the other way round and people copy `contents` into a pin, which always disagrees |
| A dependency hands over skills, agents, commands and hooks only | `CONTENT_DIRS` in `build.py` is what stops a dependency writing anywhere it likes in the output |

A shipped folder can never itself be a dependency `path`. `MANIFEST_NAME` is in `NEVER_SHIP`, so
nothing that ships carries a manifest and `read_manifest` refuses it. A dependency is always a
source checkout.

## What a neutral hook rule is

`hooks/hooks.yaml` is a list of blocks. It never ships: every harness with a hook surface has its
own event vocabulary, so an emitter that carries hooks translates this file and removes it.

| Key | Is |
|---|---|
| `at` | one of `session-start`, `before-tool`, `after-tool`, `session-end`, the four moments five harnesses have in common |
| `run` | a path to a file inside the plugin. Not a shell line, so the build can check the hook has something to run. Shell work goes inside that file |
| `match` | optional, one pattern, passed to whatever the harness calls a matcher |

Any other key is refused rather than ignored, because an ignored key in a guard is a guard that does
less than it appears to.

**The moment is `at` and never `on`.** YAML 1.1 resolves a bare `on` to the boolean true, in every
YAML 1.1 reader, so `on: session-start` arrives keyed `true` and the rule names no moment. It was
written as `on` and nothing noticed for as long as nothing read a rule. A rule still written that
way is refused by name, so the author is told this rather than told they have a key called True.

## Adding a harness is one module and one registry line

Everything to the left of the seam is the build tool that already existed: resolution,
fingerprinting, collisions, the `provides` check. Everything to the right is one harness's folder.
A module in `scripts/emitters/` declares three names and nothing else.

| Name | Is |
|---|---|
| `TARGETS` | the harness names this module emits, as a tuple. One module may serve several harnesses that share a package shape |
| `CAPABILITIES` | one `Capability` per name in `TARGETS`, each naming what that harness carries and, for everything else, the sentence saying why it cannot |
| `emit(target, manifest, tree)` | writes that harness's folder, in place, in the private copy of the staged tree it is handed. Returns nothing |

Adding a harness is that module plus one line in `REGISTRY` in `emitters/__init__.py`. Nothing else
in Foundry changes. `claude_code.py` is under forty lines including its docstring, which is the
evidence the seam is in the right place.

`KINDS` in `resolve.py` is the six things a capability answers for. The first four are
`CONTENT_KINDS`, directories, and the only things a dependency may hand over.

| Kind | Where it lives in the neutral tree |
|---|---|
| `skills`, `agents`, `commands`, `hooks` | a directory at the tree root |
| `mcp` | the plugin's own `mcp.json` at the tree root, never taken from a dependency |
| `allowed-tools` | a frontmatter field inside a skill, not a thing on disk of its own |

Carrying a kind is not the same as copying it through. `claude_code.py` translates two neutral
files into the names Claude Code opens, and removes the neutral one each time.

| Neutral | Claude Code reads | Also changed |
|---|---|---|
| `mcp.json` | `.mcp.json` | only `mcpServers` crosses over. `$schema` names the portable specification the source was written against, and Claude Code's format does not name it |
| `hooks/hooks.yaml` | `hooks/hooks.json` | the four moments become `SessionStart`, `PreToolUse`, `PostToolUse`, `SessionEnd`. Only the file goes: `hooks/` is a content directory and the scripts the rules run live in it |
| both | | `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` become `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}`. Claude Code knows nothing of the shorter pair, which would reach a user as literal text inside a path |

Transports need no translation: Claude Code takes `streamable-http` as an alias for its own `http`,
and takes `stdio` and `sse` under those names.

| Harness | Module | Carries | Cannot carry |
|---|---|---|---|
| `agent-plugins` | `agent_plugins.py` | skills, mcp | agents, commands, hooks, allowed-tools |
| `claude-code` | `claude_code.py` | all six | nothing |
| `codex` | `agent_plugins.py` | skills, mcp | agents, commands, hooks, allowed-tools |
| `instructions` | `instructions.py` | skills, commands | agents, hooks, mcp, allowed-tools |
| `opencode` | `skills_tree.py` | skills, agents | commands, hooks, mcp, allowed-tools |
| `pi` | `skills_tree.py` | skills, commands, allowed-tools | agents, hooks, mcp |

Those numbers belong to the module and each is argued in that module's docstring against the
harness's own documentation. The policy that turns them into a refusal or a recorded drop belongs to
the framework. Change a capability in the module; never work around one in the framework.

**Before `emit` runs, the framework has already deleted every kind in that harness's `cannot`**: the
directory, or `mcp.json`, or the `allowed-tools` line out of each `SKILL.md`. So no emitter contains
loss logic, and none can: an emitter cannot see what its harness cannot carry.

| An emitter may | An emitter may not |
|---|---|
| Add files, write its harness's manifest, translate a neutral file into the shape that harness reads, delete a neutral file that harness does not read | Resolve, fetch, reorder, reach outside the tree it was given, or touch a fingerprint |

Every manifest goes through `write_json` in `contract.py`, and every other shared piece of file work
has a helper there. An emitter that formats its own JSON drifts one release at a time, and the drift
lands in a `contents` fingerprint looking like a content change.

**The one refusal that belongs to an emitter is about content, not about kinds.** A transport the
harness rejects, a matcher it ignores, a blocking hook it cannot express: those depend on what is
inside a file rather than on which kind it is, so the emitter raises `EmitError` itself while it is
looking at the file. Kind-level loss is never an emitter's to decide.

## Version discipline

`VERSION` is Foundry's public promise, and consumers who are strangers pin against it.

| Number | Meaning | Who bumps it |
|---|---|---|
| First | Something that used to work no longer does. The only breaking-change signal there is | Pi, on his explicit ask only |
| Second | New capability, nothing broken | Pi, on his explicit ask only |
| Third | A fix | Claude, when shipping one |

A first-number bump needs a migration document at `docs/migrations/foundry-<old>-to-<new>.md`,
because `resolve.py` names that exact path when it refuses to build across one. That directory does
not exist yet and must be created with the first such bump.

A careless second-number bump that actually breaks a consumer destroys the only break signal that
exists.

## Running the checks

There is no dependency install beyond pyyaml. The suite under `tests/` is the gate on the rules;
building the template is the end-to-end check.

```
python3 -m unittest discover -s tests
python3 scripts/build.py template --check
python3 scripts/resolve.py template --print
```

`--check` builds into a temporary directory and throws it away. All three exit 0 today, the suite at
65 tests. Run them after any change to `scripts/` or `template/`.

Python style is `ruff`, over the same four paths for both commands, before committing:

```
uvx ruff check scripts tests .github/checks template
uvx ruff format scripts tests .github/checks template
```

`ruff.toml` pins the rule set and says which two rules are left out and why. `template` is in the
list because the bootstrap stub is the one file copied by hand into every plugin repository, so it
was formatted before any repository copied it rather than after.

The four checks under `.github/checks/` each take different arguments and CI is where those
arguments are written down. Running one with the wrong path fails with a message about the path, not
about the repository, so read `.github/workflows/ci.yml` rather than guessing:

```
python3 .github/checks/discovery.py tests
python3 .github/checks/defaults.py template
python3 .github/checks/shipped.py <built> <source>
python3 .github/checks/conformance.py <built> <source>
```

The last two want a built release and the source it was built from, which CI makes by copying
`template/` to a temporary directory first so the build cannot be helped by anything sitting around
it.

The template names five harnesses, so `--check` prints five lines, one per folder, each with that
folder's own `contents` fingerprint. The version names the source and the resolution answer, never
the capability set, so a folder's fingerprint is a fact about that folder alone.

Two of the five are the same number today, and that is right rather than a bug. The template holds
no content, and OpenCode and Pi both take a loose tree with no manifest, so with nothing to lay out
there is nothing to tell the two folders apart. They separate the moment the plugin has anything:
Pi ships commands as `prompts/` and OpenCode drops them, OpenCode ships `agents/` and Pi drops them.
The one previous reason these two differed was that each carried a different set of `.gitkeep`
placeholders, which is a difference in git bookkeeping and not in what anybody installs.

The suite covers each refusal by its message text. Resolution: a pin that moves, two dependencies
wanting different builds, a Foundry too old, a different first number in either direction, a
dependency loop, two sources for one name, and a `provides` claim absent from the output. Emitting:
a kind a harness cannot carry, hooks on OpenCode and on Pi, an MCP server on Pi, a harness name
Foundry does not know, a `degrade` block naming a harness not in `targets`, an empty `targets` list,
a skill nested more than one level deep, a manifest the author already wrote being overwritten, and
the case where every named harness would drop everything the plugin holds. Hooks have four of their
own: a rule written with `on`, a moment outside the four, a `run` naming a file the plugin does not
hold, and a key a rule does not name.

It also covers the eight things that fail silently or crash rather than refusing: the author's local
`.claude` settings reaching the shipped folder, a refusal on one harness leaving a half-written
release behind, the neutral files shipping into a Claude Code folder untranslated, a `.gitkeep`
shipping into every folder and holding an empty content directory open, the sweep that removes it
reaching one level too far into a skill somebody wrote, the `.foundry` cache shipping inside every
folder, that same cache moving a plugin's pin the moment it is built once, and a previous release
being copied into the next one. Add a test there rather than checking a refusal by hand.

Two guards are worth knowing before changing anything under `scripts/emitters/`. One asserts a
Claude Code folder holds exactly the files it should, and one asserts its `contents` fingerprint is
a string written out by hand from the specification of the folder rather than read back from the
build. If either goes red and the change did not mean to move that folder, it breaks pins on
machines Foundry cannot see.

## Known stale, do not trust these until they are rewritten

| File | What is wrong |
|---|---|
| `.claude-plugin/marketplace.json` | Lists five plugins served from this repository. None of them are here. Kept on purpose, and `.claude-plugin/README.md` says why: the entries resolve from the untouched `release` branch, so deleting them would break people who already installed one. Whether a catalog of consumers belongs in the base at all is still open |
| `docs/adr/0001-materialized-plugin-bundles.md` | Describes `bundles/`, `library/`, `packages/` and `scripts/check_boundaries.py`, none of which exist. Superseded by 0002 and kept as history, which is what an ADR is for. Do not follow it |

Five files were on this list and are no longer. `template/foundry.plugin.yaml`'s pin comment now
says the pin is the fingerprint of the dependency's source checkout. `.github/workflows/ci.yml` and
`.github/workflows/release.yml` were rewritten for a base rather than a monorepo. `.gitignore` was
rewritten so every fence names something this repository can produce, which took out `/plugins/`,
`/local/`, and a per-machine path under `bundles/meditate/`. `.gitignored/` was deleted: its README
described a scratch layout naming `docs/<product>/` and `research/`, both of which left in the
split.

`v0.1.0` is tagged on this machine and has not been pushed, so the bootstrap stub cannot reach it
over the network yet. A plugin repository can still build against it today by pointing
`foundry_source:` in its manifest at this checkout, or by setting `FOUNDRY_SOURCE` to the same path,
because git clones a local directory as readily as a URL. That path is proven: a fresh copy of
`template/` builds through the stub, twice, to the same five fingerprints the in-repo `--check`
prints. Pushing the tag is Pi's call and has not been made.

## Working rules for this repo

- Documentation is structure, why, and how to operate it. No preamble, no restating the obvious.
- Never refer to a decision by a shorthand code. State the decision in a sentence every time.
- No em dashes. Use a colon, a comma, a period, or a middle dot.
- Never compare Foundry to an operating system or to any Unix-like system.
- Prefer a table to a bullet list for anything enumerable. Headings state their conclusion.
