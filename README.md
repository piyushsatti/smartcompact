# smartcompact

A deliberate, state-aware compaction boundary for Claude Code.

Claude Code compacts when a token count crosses a threshold, and a summariser
decides what survives: a median of about a tenth of the context, chosen without
knowing which of your threads are still live. Smartcompact replaces that. At a
threshold the session stops, triages its open threads, asks you a disposition
for each one, writes a handoff file per live thread, and reloads those on the
next session.

**Nothing is built yet.** This repository holds the manifest and the skeleton.
No skill, no hooks, no scripts.

## The wiki is the source of truth

Architecture, the measured behaviour this replaces, the state machines and every
decision live in the wiki, not here.

Operating model: **wiki says why · `notes/PLAN.md` says what and how · code is
what is.**

Nothing in this README restates the wiki. If the two disagree, the wiki is right
and this file is stale.

## Layout

| Path | Holds |
|---|---|
| `foundry.plugin.yaml` | What this plugin is, which harnesses it builds for, what it needs |
| `skills/` | One directory per skill, exactly one level deep, each holding a `SKILL.md` |
| `hooks/` | Hook scripts, and `hooks/hooks.yaml`, which is neutral and never ships as written |
| `agents/`, `commands/` | Unused by this plugin. Kept because the template ships them |
| `scripts/foundry.py` | Fetches Foundry and hands over to its compiler. Excluded from what ships |
| `notes/`, `tests/` | Not shipped |

## Build

```
python3 scripts/foundry.py check
python3 scripts/foundry.py build --out dist
```

`check` builds into a temporary directory and throws it away. That is what CI
runs on every push. `build` writes `dist/`, which for this plugin is one folder,
`claude-code`, carrying its own `foundry.lock.json`.

Built with [Foundry](https://github.com/piyushsatti/foundry), pinned in the
manifest. The compiler is fetched at build time and is never committed here.

## Why Claude Code only

Hooks are most of this product, and of the six harnesses Foundry emits, only
`claude-code` carries hooks at all. A folder for any other harness would install,
report success, and do none of the things this plugin exists to do.
