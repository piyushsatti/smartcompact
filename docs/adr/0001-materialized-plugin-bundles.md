# ADR 0001 — Materialized plugin bundles

**Status:** accepted (2026-07-12) · **Decided by:** Pi, after a red-vs-blue adversarial review of the migration plan.

## Decision

Foundry develops in a modular DRY source tree and ships self-contained plugin bundles built from it:

- `bundles/<name>/` — tracked source of truth per plugin (skills, agents, hooks, server, `bundle.yaml`).
- `library/{skills,agents}/` — shared-capability promotion target. Starts empty; a capability moves here only when a **second** bundle needs it (Rule of Three), and consumers pull it back via `compose:` in `bundle.yaml`.
- `packages/` — shared code libraries, vendored into bundles at build (package tree + declared `sidecars`, e.g. `schema.sql`).
- `plugins/` — **gitignored build output.** `scripts/build.py` materializes it; the release workflow publishes it to the `release` branch; `marketplace.json` on `main` points each plugin there via `git-subdir` sources (`ref: release`).
- Invariant, CI-enforced (`scripts/check_boundaries.py`): a bundle may reference `library/` and `packages/`, **never another bundle's internals by path**. Namespaced runtime dispatch between plugins stays legal.

## Why

1. **Materialize-copy over symlinks** (CC dereferences in-marketplace symlinks at install, so symlinks were viable): physical copies give independent per-bundle versioning — two bundles may ship different vintages of a shared capability — and survive hosts/tools that don't dereference. Cost: a build step; accepted.
2. **Gitignored output + release ref over committing built plugins to main**: main stays fully DRY (no committed duplication to drift); the served artifact is produced by one gated workflow instead of hand-maintained copies. Cost: main alone isn't installable — installs come from `release`; accepted.
3. **Local-until-shared over a day-one shared library**: every skill today has exactly one consuming bundle, so a pre-built shared library would be indirection with no dedup (Fowler's Rule of Three; Metz's "wrong abstraction"; Nx's "shared library is a lie"). The boundary guard makes promotion the only legal reuse path, which keeps the hybrid honest.
4. **Version in `plugin.json` only** — the generated catalog carries no version key; a duplicate silently masks bumps (documented CC resolution order).

## Consequences

- Shipping a content change **requires a version bump** — `claude plugin update` is version-gated, not sha-gated. A shared `library/` capability change requires bumping every consumer (manual now; automate later).
- `_vendor/` no longer exists on main; the manifold MCP resolves `packages/manifold` via its tier-2 parent-walk in-repo. Install-shape (tier-3) verification must run the built plugin **outside** any foundry checkout, or the parent-walk masks a broken vendor step.
- Rollback of a bad ship = repoint `release` to the last good sha; installs are pull-based and recover on the next marketplace update.
- Drift is machine-checked: build-twice determinism + vendored==source fidelity (`tests/test_build_determinism.py`) and the boundary fixture (`tests/test_check_boundaries.py`) run in CI.
