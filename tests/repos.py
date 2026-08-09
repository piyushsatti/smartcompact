"""Throwaway plugin repositories, written into a temporary directory per test.

Fixture trees are not checked into this repo. A checked-in fixture is a second
copy of the plugin shape that drifts from `template/` without anyone noticing,
and it has to be read from disk to be understood. Building each one in the test
that needs it keeps the shape visible at the point it is used, and cleanup is
the temporary directory going away.

Everything here is fixture plumbing. The rules being tested live in
`tests/scripts/test_resolve.py`, `tests/scripts/test_build.py` and
`tests/scripts/test_emitters.py`.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build  # noqa: E402  the tool under test, imported the way it imports itself
import resolve  # noqa: E402

MANIFEST_NAME = resolve.MANIFEST_NAME

# The Foundry this checkout is. Fixtures default to it so an ordinary build
# passes, and the version rules are exercised by handing the check functions an
# explicit version instead of touching this file.
RUNNING_FOUNDRY = (REPO_ROOT / "VERSION").read_text().strip()


def make_repo(
    workspace: Path,
    plugin_id: str,
    *,
    version: str = "0.1.0",
    foundry: str = RUNNING_FOUNDRY,
    description: str | None = None,
    requires: list[dict] = (),
    provides: dict | None = None,
    exclude: list[str] = (),
    files: dict[str, str] | None = None,
    targets: list[str] | None = None,
    degrade: dict[str, dict] | None = None,
    metadata: dict | None = None,
) -> Path:
    """One plugin repository at `workspace/plugin_id`, returned as its root.

    `files` maps a path relative to the repo root to its text, so a fixture
    reads as the tree it is. The manifest is written last and always.

    `targets` and `degrade` are written only when a fixture passes them, so the
    manifest a fixture gets by default is one that never mentions either key.
    That default is the whole compatibility case: it has to keep producing the
    folder Foundry produced before harnesses were a thing, and a fixture that
    quietly wrote `targets: [claude-code]` would test a different manifest and
    pass while the case it was named for broke.

    `metadata` carries the descriptive fields, which every emitter writes into
    its own manifest, so one fixture can be checked against several of them.
    """
    root = workspace / plugin_id
    root.mkdir(parents=True, exist_ok=True)

    for relative, text in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    manifest: dict = {"id": plugin_id, "version": version, "foundry": foundry}
    if description:
        manifest["description"] = description
    for key, value in (metadata or {}).items():
        manifest[key] = value
    manifest["requires"] = {"plugins": [dict(entry) for entry in requires]}
    if provides:
        manifest["provides"] = provides
    if exclude:
        manifest["exclude"] = list(exclude)
    if targets is not None:
        manifest["targets"] = list(targets)
    if degrade is not None:
        manifest["degrade"] = degrade

    (root / MANIFEST_NAME).write_text(yaml.safe_dump(manifest, sort_keys=False))
    return root


def needs(dependency: Path, *, take: dict | None = None, pin: str | None = None) -> dict:
    """A `requires.plugins` entry pointing at a sibling repo.

    The pin defaults to that repo's real fingerprint, which is what a correct
    manifest holds. Tests about disagreement pass a wrong one on purpose.
    """
    entry = {
        "id": dependency.name,
        "pin": pin or resolve.fingerprint(dependency),
        "path": f"../{dependency.name}",
    }
    if take:
        entry["take"] = take
    return entry


def files_under(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


class RepoCase(unittest.TestCase):
    """A test with a temporary workspace that cleans itself up."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory(prefix="foundry-tests-")
        self.addCleanup(holder.cleanup)
        self.workspace = Path(holder.name).resolve()

    def destination(self, name: str = "dist") -> Path:
        return self.workspace / "_built" / name

    def ship(self, plugin: Path, out: Path) -> str:
        """Build, and hand back whatever the build printed.

        Emitters print what they left behind, and that report is the only place
        some losses are ever stated, so a test that lets it go to the terminal
        both throws away the assertion and buries the next test's output in it.
        """
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            build.build(plugin, out)
        return printed.getvalue()
