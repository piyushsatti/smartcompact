# marketplace.json still works, because only `name` and `source` were frozen

Anyone who ran `/plugin marketplace add piyushsatti/foundry` reads `marketplace.json` from the
default branch of this repository. Deleting it, or emptying its plugin list, breaks those people.
So it stays, listing five plugins whose source no longer lives here.

## An install resolves against `name` and `source`, so only those two are frozen

Nothing resolves against `description`. It is display text.

| Field | Safe to edit | Because |
|---|---|---|
| `description`, at any level | Yes, freely | Display text only. Editing it cannot break an existing install or a fresh `marketplace add` |
| An entry's `name` | No | It is the identity a user installed against. Changing it makes the plugin look removed rather than moved |
| An entry's `source` | Not until that plugin has a repository of its own | It is what a fetch reads. The repointing steps are below |
| Top-level `name` and `owner` | No | They identify the marketplace itself, which is what `plugin@marketplace` names |

Both em dashes this catalog carried sat in `description` strings and were removed on that basis,
the repo banning them outright. Every `name` and every `source` object was left byte-identical.

## It works because the entries never pointed at the default branch

Every entry is a `git-subdir` source with `ref: release`. The `release` branch was not touched
when the plugins moved out, and still holds all five built plugin folders. Nothing a user does
reads a plugin from the default branch.

| What a user does | What happens today |
|---|---|
| Adds the marketplace | Reads this catalog from the default branch and sees five plugins |
| Installs one | Fetches the built folder from the `release` branch, which is still there |
| Updates one | Gets the same build back. Nothing writes to that branch any more |

## Three things are inconsistent, and each is accepted on purpose

| The inconsistency | Why it is accepted |
|---|---|
| The catalog lists plugins whose source is not in this repository | The entries still resolve, and removing them would break people who have them installed |
| Nothing on the default branch can rebuild the `release` branch | The workflow that built it went out with the plugins |
| The `release` branch is frozen | Nothing writes to it, which is exactly what keeps the five entries working |

The cost is that a fix to any of the five cannot reach an installed copy until that plugin has a
repository of its own. That was accepted when the plugins moved out.

## What has to happen once the five plugin repositories exist

| Step | Detail |
|---|---|
| 1 | Repoint each entry's `source` at that plugin's own repository, pinned to a release tag there |
| 2 | Leave each entry's `name` exactly as it is |
| 3 | Confirm every entry resolves from its new repository |
| 4 | Delete the `release` branch. It exists only to keep these five entries working |

Step 2 is the one that matters. The name is the identity a user installed against, so changing it
makes the plugin look removed rather than moved.

## Whether this catalog belongs in Foundry at all is still open

Foundry keeps no list of consumers and never reaches into another repository. This file is a list
of consumers. It is here because it was here first and moving it costs the people using it, not
because a catalog belongs in the base. Whether it moves to its own repository is a decision for
the session that creates the five plugin repositories.
