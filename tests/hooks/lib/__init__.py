"""Puts `hooks/` on the path, so these tests import the library the way a hook does.

Claude Code runs a hook by absolute path, with no package context and an
unrelated working directory, so a hook reaches its own library by putting
`hooks/` on `sys.path` and importing `lib`. Every test module here does the
same, which means the import mechanism itself is under test rather than
assumed.

It also removes a trap. `tests/` mirrors the source tree by house rule, so
`tests/hooks/lib/` and `hooks/lib/` are both importable as `hooks.lib`, and
`unittest discover -s tests` puts `tests/` on the path first. A test importing
`hooks.lib` therefore gets this empty package instead of the real one, with no
error until a symbol is missing. Importing `lib` cannot collide with anything.
"""

import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[3] / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
