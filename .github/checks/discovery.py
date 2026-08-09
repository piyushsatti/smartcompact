#!/usr/bin/env python3
"""Every test file on disk is a test file unittest actually found.

Tests are discovered rather than named module by module, which is right: a
suite listed by hand in a workflow stops covering the file somebody added last
week. The cost of discovery is that it fails silently. `unittest` walks past
any directory without an `__init__.py`, and a run that finds nothing still
exits 0, so a whole directory of tests can stop running and the build stays
green.

Counting the tests it found does not catch that. The directory that went
missing takes its own count with it and the remaining files still report a
healthy number, so the only honest check is the one that names the files. This
compares what discovery returned against every `test_*.py` on disk and reports
the difference by path.

A module that raises on import is reported separately. `unittest` turns one
into a placeholder test that fails, which the run catches, but the message
reads as a broken test rather than as a module nobody is running, so it is
worth saying plainly here.

Operate:
    python3 .github/checks/discovery.py [TESTS_DIR]
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def module_path(name: str, root: Path) -> Path:
    """`tests.scripts.test_build` back to the file it was loaded from."""
    return root.joinpath(*name.split(".")).with_suffix(".py")


def discovered(tests: Path, top: Path) -> tuple[set[str], list[str], int]:
    """Every module discovery loaded, every module it could not, and the count.

    `top_level_dir` is the repository root rather than the tests directory, so
    a module comes back as `tests.scripts.test_build` and maps straight onto a
    path. Discovering from inside `tests/` returns `scripts.test_build`, which
    names a directory that is not where the file is.
    """
    loader = unittest.TestLoader()
    suite = loader.discover(str(tests), top_level_dir=str(top))
    modules: set[str] = set()
    count = 0

    def walk(node) -> None:
        nonlocal count
        for item in node:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                modules.add(type(item).__module__)
                count += 1

    walk(suite)
    return modules, list(loader.errors), count


def main() -> int:
    tests = Path(sys.argv[1] if len(sys.argv) > 1 else "tests").resolve()
    top = tests.parent
    if not tests.is_dir():
        sys.exit(f"no {tests} directory, so there is no suite to discover.")

    on_disk = sorted(tests.rglob("test_*.py"))
    if not on_disk:
        sys.exit(
            f"no test_*.py files under {tests}.\n"
            "  This job would pass having run nothing, which is the failure it exists\n"
            "  to catch. Either the tests moved, or they were deleted."
        )

    modules, broken, count = discovered(tests, top)
    found = {module_path(name, top).resolve() for name in modules}
    missed = [path for path in on_disk if path.resolve() not in found]

    if broken:
        print("\n".join(broken), file=sys.stderr)
        sys.exit(
            f"{len(broken)} test module(s) could not be imported, printed above.\n"
            "  Discovery turns each one into a placeholder that fails, so the run reports\n"
            "  a broken test rather than a module nobody is running. Fix the import."
        )

    if missed:
        listed = "\n".join(f"    {path.relative_to(top)}" for path in missed)
        sys.exit(
            f"{len(missed)} test file(s) exist and were not discovered:\n\n"
            f"{listed}\n\n"
            "  unittest walks past any directory without an __init__.py and says nothing,\n"
            "  so these ran nowhere and this job would otherwise have passed.\n\n"
            "  Add an __init__.py to every directory on the way down to each file, or\n"
            "  move the file under a directory that already has one."
        )

    print(f"discovered {count} tests across {len(on_disk)} files, and {len(on_disk)} exist on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
