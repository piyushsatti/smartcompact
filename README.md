# foundry

Foundry is the base an agent plugin is built on. It holds exactly two things: the tooling that turns
a plugin repository into a shippable folder for each agent harness that plugin names, and the
template a new plugin repository starts from.

It holds no plugins. Every plugin lives in its own repository, with its own version and its own
releases.

You write the plugin once. The build writes one folder per harness: Claude Code, the portable Agent
Plugins package that Codex and Cursor and GitHub Copilot and VS Code read, a loose skills tree for
OpenCode and for Pi, and a set of repository instruction files. What no harness can carry is
reported, never quietly left out.

## What is in here

| Path | Holds |
|---|---|
| `scripts/resolve.py` | Works out what a plugin needs: which Foundry version applies, which dependencies are in play, the fingerprint of each |
| `scripts/build.py` | Assembles the content once, then hands it to one emitter per harness, and writes `foundry.lock.json` inside every folder |
| `scripts/emitters/` | One module per harness, plus the loss policy that is the same for all of them |
| `template/` | The starting shape of a plugin repository |
| `template/scripts/foundry.py` | The bootstrap stub each plugin repo carries: reads the declared Foundry version, fetches that release, hands over to the build tool |
| `VERSION` | Foundry's own version |
| `docs/adr/` | The decisions and the reasoning behind them |

## Anyone can build on it

Foundry does not know who uses it, keeps no list of consumers, and never reaches into anyone's
repository. Third-party consumers are first-class. Three things follow from that.

| Consequence | What it means in practice |
|---|---|
| Foundry cannot govern what people share | Two parties who want to share code make their own repository and point at it. Foundry has no opinion and no involvement |
| Foundry's version number is a public promise | A breaking change shipped as a small bump breaks strangers silently. Version discipline is the contract, not housekeeping |
| Foundry cannot notify anyone | It publishes a release. Consumers watch it and upgrade when they choose |

## Resolution happens once at publish time, never on a user's machine

| Step | Where | What happens |
|---|---|---|
| 1 | The plugin's own repository, in its own CI | The build tool resolves everything the plugin needs and settles on one Foundry version |
| 2 | Same run | It writes one self-contained folder per harness the plugin named, each with its own `foundry.lock.json` recording exactly what went into it |
| 3 | The plugin's repository | Those folders are published as one release under the plugin's own version |
| 4 | A user's machine | The folder for that person's harness is downloaded and used as it arrived |

Nothing is built, fetched or resolved where a plugin is installed, so nothing can conflict there.
Two plugins that ship different builds of the same skill are two folders that never meet.

The lock file is history, not instructions. Nothing reads it back to reproduce a build. It exists
so that when a shipped plugin misbehaves, what it was built from is a fact rather than a
reconstruction.

## Starting a plugin repository

Copy the template into a new empty repository and build it once before changing anything.

```
cp -R template/ ../my-plugin
cd ../my-plugin
git init
python3 scripts/foundry.py check
```

The stub fetches the tag `v<version>` from the Foundry repository, taking `<version>` from the
`foundry:` line of the manifest, and caches the release in `.foundry/`, which is never committed. So
a plugin repository can only build once that tag is published. None is published yet. Until the
first one is cut, build against a Foundry checkout directly:

```
python3 <path-to-foundry>/scripts/build.py . --check
```

Then edit `foundry.plugin.yaml`: set `id`, `version` and `description`, name the harnesses under
`targets`, and list what the plugin hands over under `provides`. Skills go in `skills/`, one
directory each, exactly one level deep. Agents go in `agents/`, one file each. Commands go in
`commands/`, one file each. Hooks go in `hooks/hooks.yaml`, one block each naming `at`, `run` and
optionally `match`. MCP servers go in `mcp.json` at the repository root. Anything development-only
goes under `exclude` so it stays out of what people download.

Those last two are neutral forms and neither ships as written. Every harness with a hook surface has
its own event vocabulary, and Claude Code reads its MCP servers from `.mcp.json` rather than
`mcp.json`, so the emitter for each harness translates what it carries and removes the neutral file.
A folder never holds a file that harness does not read.

| Command | Does |
|---|---|
| `python3 scripts/foundry.py check` | Builds into a temporary directory and throws it away. This is what the template's CI runs on every push |
| `python3 scripts/foundry.py build --out dist` | Writes `dist/`, the folder or folders that get published |

## One source, one version, one folder per harness

`targets` names the harnesses. Delete the key and the answer is `claude-code`, which is exactly what
Foundry built before the key existed, in the same place, byte for byte.

| Name | Is | Reaches |
|---|---|---|
| `agent-plugins` | the portable Agent Plugins 1.0.0 package: `plugin.json` at the folder root, `mcp.json`, `skills/<name>/SKILL.md` | Cursor, GitHub Copilot, VS Code, Kiro, ChatGPT, and Codex |
| `claude-code` | `.claude-plugin/plugin.json`, `.mcp.json`, `hooks/hooks.json`, and every kind Foundry models | Claude Code |
| `codex` | the portable package plus `.codex-plugin/plugin.json`, which is what Codex reads today | OpenAI Codex |
| `instructions` | `AGENTS.md` naming this plugin's skills and commands, plus a `CLAUDE.md` and a `GEMINI.md` pointing at it | every harness, by a different route: see below |
| `opencode` | a loose tree, `skills/` and `agents/`, no manifest at all | OpenCode |
| `pi` | a loose tree, `skills/` and `prompts/`, no manifest at all | Pi |

With one name, or none, the folder written to `--out` is the plugin. With two or more, `--out` holds
one complete folder per harness, each with its own lock file, plus `foundry.release.json` listing
every folder's `contents` fingerprint and everything that folder had to leave out. One tag, one
version, one resolution answer.

The same version across those folders means the same source tree, the same dependency pins and the
same Foundry. It does not mean the same contents, and the per-harness fingerprint differs by
construction. The folder is the thing people install, so the folder is the thing that gets a name.

`instructions` is not a package and the difference matters. Every other folder is installed. That
one is copied into a repository somebody already owns, and from that moment nothing installs it,
updates it or removes it. A later version of the plugin does not reach the copy. No surveyed harness
lets a package carry a repository instructions file, so this is the only route there is, and a
plugin that ships one has to say this in its own README rather than call it support.

## A refusal is the normal answer when a harness cannot carry something

Harnesses differ. Pi has no MCP surface. Agent Plugins 1.0.0 defines no agent, command or hook
component. OpenCode has no declarative hooks. When a plugin declares a kind a named harness cannot
represent, the build stops and names the kind, the harness, the manifest line, and both ways
forward:

```
CANNOT SHIP THIS TO PI.

  mcp/manifold is declared in foundry.plugin.yaml, and Pi has no MCP surface.

  Either drop pi from 'targets', or write it down under
  'degrade.pi.drop: [mcp]' so the loss is on the record.
```

**That is the tool working, not a bug.** Every failure in this space is otherwise silent: the folder
installs, reports success, and does less than its README says. Refusing is the only outcome that
reaches the person who can decide.

`degrade` is how you decide. Naming a kind under `degrade.<harness>.drop` pre-authorises that loss
on that harness, and then the build prints it, writes it into that folder's `foundry.lock.json`, and
writes it again into `foundry.release.json`.

```yaml
degrade:
  agent-plugins:
    drop: [agents, commands, hooks]
  opencode:
    drop: [commands]
  pi:
    drop: [mcp]
```

There is no third outcome and Foundry never decides by itself. A folder that is missing something is
always a line somebody wrote. The second way forward is deliberately more work than the first,
because writing a loss down should feel like a decision. Read the refusal before writing the line:
for a plugin whose whole product is an MCP server, a Pi folder with `mcp` dropped is an empty
wrapper.

A loss agreed to months ago is still a loss shipping today, which is why every recorded drop is
printed again on every build. The person watching the build is the last one who can notice.

## A dependency is another plugin's repository, pinned by fingerprint

Add the other plugin under `requires.plugins`. Every entry needs all three of these.

| Key | Is |
|---|---|
| `id` | The dependency's id, the same one its own manifest declares |
| `pin` | One exact fingerprint. A moving target such as `latest`, `main` or `*` is refused |
| `path` | Where to find that repository at build time, relative to this one |

`take` is the optional fourth key and lists what gets copied in. A dependency hands over skills,
agents, commands and hooks, and nothing else, so it can never write outside those directories.
Leaving `take` off pins the dependency and copies nothing from it.

The pin names the fingerprint of the dependency's repository as checked out at build time, not of
the folder that plugin ships. The build reads the dependency's own source, so the source is what the
pin is checked against. Two consequences worth knowing before you write one:

| Consequence | Detail |
|---|---|
| The `contents` value in a plugin's lock file is not a pin | It fingerprints what that plugin shipped, a different set of files from its source, so it is a different number. No pin is ever compared against it |
| `path` points at a repository, never at a built folder | A shipped folder carries no manifest, because the manifest is one of the files that never ships, so the build cannot read one |

Nothing prints the fingerprint on its own yet. Two ways to get it:

| Situation | Where the number is |
|---|---|
| The dependency already builds somewhere | The `build` value recorded for it under `dependencies` in that build's `foundry.lock.json` |
| Pinning it for the first time | Write any placeholder pin and run the build. The refusal reports the fingerprint of the copy on disk: `expects <id> build <placeholder>, but the copy here is build <fingerprint>` |

The fingerprint covers the whole checkout, so a stray uncommitted file in the dependency's working
tree changes it. Pin against a clean checkout.

One thing a build leaves behind is exempt, and it has to be. The `.foundry` cache the bootstrap stub
writes appears on a repository's first build and never leaves, so if it counted, no repository that
had ever been built could be pinned against and the advice above would describe a state nothing can
return to. It is outside the fingerprint.

The output directory is not exempt, because Foundry does not know its name: `--out` takes anything,
and treating `dist` as special would be a guess about somebody else's repository. So delete the
output directory, or build somewhere outside the tree, before reading a pin off a checkout.

## What the build refuses to do, and why

The build never picks a winner. Every case below stops it, names both sides, and says what to do.

| The build stops when | Why |
|---|---|
| A plugin needs a Foundry whose first number differs from the one building it | A change to the first number is the only signal that something which used to work no longer does. It cannot be worked around, only migrated, so the message names the migration document to read |
| A plugin needs a Foundry newer than the one building it | Nothing is upgraded or downgraded behind your back. Build with a newer Foundry, or lower the requirement on purpose |
| A dependency pin is a moving target such as `latest`, `main` or `*` | A pin has to mean the same thing tomorrow as it does today. Following a moving target is how a plugin ends up shipping against something it was never built with |
| Two plugins in the tree want different builds of the same third plugin | A real disagreement with no correct answer. Choosing the newer one silently would mean nobody finds out a substitution happened |
| Two dependencies hand over an item with the same name | Only one can ship. Rename one, or stop taking one of them |
| A plugin claims under `provides` something the built folder does not contain | The claim is metadata other people read, so an empty one is a lie in public |
| The dependency graph contains a loop | Reported as the actual loop, so it can be broken |
| The output directory holds files this tool did not write | It refuses to delete someone else's directory |
| A named harness cannot represent a kind the plugin declares, and no `degrade` line says so | The absence would be invisible: the folder installs, reports success and does less than it says |
| Every named harness would drop everything the plugin holds | Every folder in the release would be an empty wrapper |
| `targets` names a harness Foundry does not emit, or is an empty list | A misspelled name that quietly built nothing is how a release ships without the folder somebody was promised |
| `degrade` names a harness that is not in `targets`, or a kind that is not a kind | A waiver that looks written and fires on nothing is worse than no waiver |
| A skill directory sits more than one level under `skills/` | Some harnesses look one level down and some recurse, so a nested skill installs on part of the list and is invisible on the rest, with no error anywhere |
| An emitter would write a manifest the author already wrote by hand | Foundry does not overwrite somebody's file to make room for its own |

The harness checks all run before any folder is written, so a release that cannot ship one of its
folders leaves none of them behind. Half a release is worse than none: the folders that did appear
look complete.

## How the Foundry version is chosen

| Rule | Detail |
|---|---|
| A plugin declares the oldest Foundry it works with | `foundry: 0.1.0` means 0.1.0, or any later release keeping the same first number |
| The build picks the newest version anything in the tree actually asked for | Never newer than that, so a build can never land on a version nobody requested |
| A plugin takes all of Foundry or none | There is no picking pieces. Selection would let repositories drift into incompatible subsets |
| A plugin may sit on an old Foundry indefinitely | Foundry cannot run a plugin's tests, so only that plugin can approve its own upgrade |

## License

MIT, see `LICENSE`.
