# example

An agent plugin built on Foundry. One source, built once, into one folder per
harness named under `targets` in the manifest.

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

It prints one line per harness, each with that folder's own fingerprint. The
version names the source, not the capability set, so each fingerprint is a fact
about that folder alone. Two of them being equal means those two harnesses were
handed the same files, which is what an empty repository does to `opencode` and
`pi`. It is not an error.

## Do not

- Edit `dist/`, `foundry.lock.json` or `foundry.release.json` by hand. All three
  are written by the build.
- Copy a skill out of a dependency into this repo. Take it through `requires`,
  or the copy stops receiving fixes the moment it is made.
- Commit `.foundry/`. It is a cache of fetched Foundry releases.
- Write a `degrade` line to make a red build green without reading the refusal.
  It is the only way to ship a folder that does less than this repo says, and it
  is meant to be a decision.
- Describe `opencode`, `pi` or `instructions` as installable in this plugin's
  README. The first two are loose files a person copies by hand, and the third
  goes into a repository somebody else owns and is never updated again.
