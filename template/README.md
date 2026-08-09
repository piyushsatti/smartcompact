# example

One line about what this plugin does.

## Layout

| Path | Holds |
|---|---|
| `foundry.plugin.yaml` | What this plugin is, which harnesses it is built for, and what it needs |
| `skills/` | One directory per skill, exactly one level deep, each holding a `SKILL.md` |
| `agents/` | One file per agent |
| `commands/` | One file per command |
| `hooks/hooks.yaml` | Hooks, if this plugin has any. Neutral, never shipped as written |
| `mcp.json` | MCP servers, if this plugin has any. Neutral, and Claude Code reads `.mcp.json` |
| `scripts/foundry.py` | Fetches Foundry and hands over to its build tool |
| `tests/` | Not shipped |

Skills sit exactly one level under `skills/`. Some harnesses look one level down
and some recurse, so a grouping directory would ship intact on part of the list
and hide every skill beneath it on the rest, with no error anywhere. The build
refuses one rather than let that happen.

## Writing a hook

`hooks/hooks.yaml` is a list of blocks. It is a neutral form and it never ships:
every harness with a hook surface has its own event names, so the emitter for
each one translates this file and removes it.

```yaml
- at: before-tool
  match: Bash
  run: hooks/guard.sh
```

| Key | Is |
|---|---|
| `at` | one of `session-start`, `before-tool`, `after-tool`, `session-end` |
| `run` | a path to a file in this repository, not a shell line |
| `match` | optional, one pattern |

Those four moments are what every harness has in common. A moment outside them
cannot be written for all of them, and a hook that does not fire is a guard that
is not there, so the build refuses one rather than approximate it.

`run` is a path so that the build can check the file is really there and really
ships. Put any shell work inside that file. Note that `exclude` in the manifest
lists `scripts`, so a hook script belongs somewhere that ships, such as beside
the rules in `hooks/`.

Write the moment as `at` and never as `on`. YAML reads a bare `on` as the
boolean true, so `on: before-tool` arrives naming no moment at all. The build
refuses that by name rather than leaving you to find it.

## Build

```
python3 scripts/foundry.py check
python3 scripts/foundry.py build --out dist
```

`check` builds into a temporary directory and throws it away, which is what CI
runs on every push. `build` writes `dist/`: one self-contained folder per
harness named under `targets`, each with its own `foundry.lock.json` recording
exactly what went into it, plus `foundry.release.json` naming every folder, its
fingerprint, and anything that folder had to leave out. With one harness named,
or none, `dist/` is that folder itself.

Those folders are what gets published and what people install. Nothing is
resolved on the machine of whoever installs it. They get the folder.

## Which harnesses this plugin is built for

`targets` in the manifest names them. Delete the key and the answer is
`claude-code` alone.

| Name | What that folder is | Who reads it |
|---|---|---|
| `agent-plugins` | the portable Agent Plugins 1.0.0 package | Cursor, GitHub Copilot, VS Code, Kiro, ChatGPT |
| `claude-code` | `.claude-plugin/plugin.json` and every kind Foundry models | Claude Code |
| `codex` | the portable package plus the manifest Codex reads today | OpenAI Codex |
| `instructions` | `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` | anything, by a different route: see below |
| `opencode` | a loose tree of `skills/` and `agents/`, no manifest | OpenCode |
| `pi` | a loose tree of `skills/` and `prompts/`, no manifest | Pi |

One source, one version number, one release. The same version across those
folders means the same source and the same dependencies. It does not mean the
same contents, and each folder's fingerprint is a fact about that folder alone.

Two folders showing the same fingerprint is not an error. It means those two
harnesses were handed the same files, which is what happens to `opencode` and
`pi` in a repository that has no content yet. They separate as soon as it does.

`opencode` and `pi` are loose files rather than packages. Neither harness has an
install command, a version or an update path, so a person copies the folder's
contents into a configuration directory by hand. Say that in this README rather
than claiming support.

`instructions` is not a package at all. It is copied into a repository somebody
already owns, and nothing then installs it, updates it or removes it: a later
version of this plugin does not reach the copy. No harness lets a package carry
a repository instructions file, so this is the only route there is.

## When a harness cannot carry something, the build stops

Harnesses differ. Agent Plugins 1.0.0 covers skills and MCP servers and leaves
agents, commands and hooks outside version 1. Pi has no MCP surface. OpenCode
has no declarative hooks. Declare one of those and name that harness, and the
build refuses:

```
CANNOT SHIP THIS TO PI.

  mcp/manifold is declared in foundry.plugin.yaml, and Pi has no MCP surface.

  Either drop pi from 'targets', or write it down under
  'degrade.pi.drop: [mcp]' so the loss is on the record.
```

**That is the normal answer, not a bug.** The alternative is a folder that
installs, reports success and does less than this README says, which nobody
finds out about.

Take the two ways forward literally. Removing the harness from `targets` is one
line. Writing the loss down under `degrade` is a block, and it is more work on
purpose, because a diminished folder should feel like a decision:

```yaml
degrade:
  pi:
    drop: [mcp]
```

A recorded drop is printed on every build and written into that folder's lock
file and into `foundry.release.json`. Read the refusal before writing the line.
If an MCP server is the whole point of this plugin, a Pi folder without it is an
empty wrapper and dropping `pi` from `targets` is the honest answer.

## Depending on another plugin

Add it under `requires.plugins` in the manifest with an exact pin, taken from
the `contents` value in that plugin's own lock file, and list what to take. A
pin never points at a moving target: it has to mean the same thing tomorrow.

If two things you depend on hand over something with the same name, or expect
different builds of the same third plugin, the build stops and names both
sides. It does not pick one.
