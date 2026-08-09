#!/usr/bin/env python3
"""How a check says what it found, in one place so every check says it the same.

A check that stops at the first fault sends somebody round the loop once per
fault, and each loop is a push and a wait. So problems are collected and printed
together, under a line naming the thing that turned out not to be true.

The sentence a check passes to `finish` is the claim it was making, written as a
statement rather than as a job name. On success it is what the log says was
proved; on failure it is what the log says is not true, followed by every reason.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass
class Report:
    """Problems found, each one a sentence naming the folder and the fix."""

    problems: list[str] = field(default_factory=list)

    def wrong(self, message: str) -> None:
        self.problems.append(message)

    def finish(self, claim: str) -> None:
        """Print the claim, or exit naming everything that makes it false."""
        if self.problems:
            sys.exit("\n".join([f"{claim} is not true:", ""] + [f"  {line}" for line in self.problems]))
        print(claim)
