# smartcompact

A deliberate, state-aware compaction boundary for Claude Code, built on Foundry.

## The wiki is the source of truth, and this file never restates it

Architecture, the measured behaviour being replaced, the state machines, the
thresholds and every decision live in the wiki. If this file and the wiki
disagree, the wiki is right.

Operating model: **wiki says why · `notes/PLAN.md` says what and how · code is
what is.**

Before changing behaviour, read the wiki page that owns it. Before changing a
decision, read its record. A decision is cited by its conclusion, never by its
bare number.

## Rules this project adds

| Rule | Why |
|---|---|
| **The template is add-only.** Never delete a file that came from Foundry's template, even one this plugin has no use for | `agents/` and `commands/` are empty here on purpose. A plugin that prunes the skeleton drifts from every other plugin and from the template it has to keep merging with |
| **Foundry is not this project's to change.** File an issue, propose a PR, and let its own session decide | Foundry is owned elsewhere. This repo consumes it at a pinned tag and never reaches into it |
| Tests live in top-level `tests/`, mirroring the source path: `hooks/occupancy.py` is tested by `tests/hooks/test_occupancy.py` | Never colocate tests beside source |
| A hook script must not crash | A measurement hook that fails is worse than one that abstains. Missing transcript, empty transcript and first turn all report zero and exit 0 |
| Nothing hard-codes the state directory | `CLAUDE_PLUGIN_DATA` reaches a hook and is not documented as reaching a skill, so exactly one script resolves the path and everything else asks it |
| The compaction gate must stop blocking above its ceiling | Blocking past the API's real limit ends the session and loses everything unsaved. This is the one behaviour here that can destroy work |

## Rules that come from Foundry

| Rule | Why |
|---|---|
| Everything shipped is declared in `foundry.plugin.yaml` | The build checks the claim and fails if it is empty |
| Dependency pins are exact, never `latest` | A pin has to mean the same thing tomorrow |
| Bump this plugin's version when the shipped content changes | The version is what people pin against |
| The first number of `foundry:` only changes on a migration | Changing it silently is how a build breaks somewhere else |
| A skill directory sits exactly one level under `skills/` | Some harnesses look one level down and some recurse. A grouping directory would ship intact on part of the list and hide every skill under it on the rest, with no error anywhere |
| No harness-specific key goes inside a skill, an agent or a command | A `SKILL.md` here is a plain Agent Skill and stays valid when somebody copies it out by hand. Everything per-harness lives in the manifest, which never ships |
| Adding a harness to `targets` can turn a green build red, and that is the harness telling the truth | Harnesses differ in what they can carry. Read the refusal, do not work around it |
| The moment key is `at`, never `on` | YAML reads a bare `on` as boolean true, so the rule arrives naming no moment. The build refuses that by name |

## When the build refuses because a harness cannot carry something

The message names the kind, the harness, the manifest line, and two ways
forward: drop that harness from `targets`, or write the loss down under
`degrade.<harness>.drop`. There is no third answer and the build never decides
by itself.

Pick the first when the missing kind is the point of the plugin. Pick the second
when the folder is still worth shipping without it, and know that the drop is
then printed on every build and recorded in that folder's lock file and in
`foundry.release.json`. A loss agreed to months ago is still a loss shipping
today.

## Build

```
python3 scripts/foundry.py check
```

It prints one line per harness with that folder's own fingerprint. The version
names the source, not the capability set, so each fingerprint is a fact about
that folder alone.

## Staleness check list

After changing any of these, check the others:

| Changed | Check |
|---|---|
| `foundry.plugin.yaml` | The wiki's plugin-structure page, and this file's Foundry rules |
| `hooks/hooks.yaml` or any hook script | The wiki's loops and plugin-structure pages; the manifest's `exclude`, which can sweep a hook script out and make its rule refuse |
| A threshold or the ceiling | The wiki's occupancy and loops pages. These numbers appear in three places and two of them are prose |
| The ritual or a disposition | The wiki's boundary-ritual and loops pages, and the decision record if one owns it |
| The pinned `foundry:` version | The wiki's plugin-structure evidence table, `Home`, and the spine's sources |

## Do not

- Edit `dist/`, `foundry.lock.json` or `foundry.release.json` by hand. All three
  are written by the build.
- Commit `.foundry/`. It is a cache of fetched Foundry releases.
- Write a `degrade` line to make a red build green without reading the refusal.
- Describe `opencode`, `pi` or `instructions` as installable. The first two are
  loose files a person copies by hand, and the third goes into a repository
  somebody else owns and is never updated again.
