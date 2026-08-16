"""The resident map's on-disk format, in the one place that defines it.

`map.md` has exactly one writer, the boundary hook, and one reader, the
session-start hook. Those two live in different files, so the format needs a
home that is neither of them: a parser copied into both would let `map.md`
mean two different things depending on which hook opened it, and the copies
drift silently because nothing compares them.

The writer is the boundary rather than the end of a session, ruled
2026-08-16. Two consequences worth knowing before changing it: the map is at
its freshest at the one moment anything reads it, which is session-start
after a compaction; and a session that never compacts never updates its map,
which is the price paid for having exactly one writer.

**The format itself is not settled.** It was invented while building, because
nothing in the wiki or the ledger defines it, and both `HANDOFF-6` and
`RITUAL-4` are open. Treat what follows as a placeholder with one virtue: it
is a placeholder in a single file, so replacing it is one edit rather than a
hunt through the hooks.
"""

HANDOFF_PREFIX = "hnd."
HANDOFF_SUFFIX = ".md"

# What a row means when a thread has no handoff yet. Written out rather than
# left blank so a human reading the file sees the gap instead of a cell that
# looks like a formatting slip.
NO_HANDOFF = "(none)"


def parse(text):
    """{thread: (handoff_filename_or_None, attention)} from the table rows.

    Anything that is not a three-cell row is skipped rather than refused. The
    header, the separator, the prose above the table and blank lines all fail
    that shape harmlessly, so none of them needs a case of its own, and a
    `map.md` a human has scribbled a note into still parses.
    """
    rows = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        name, handoff, attention = cells
        if not name or name == "thread" or set(name) == {"-"}:
            continue
        try:
            count = int(attention)
        except (TypeError, ValueError):
            count = 0
        rows[name] = (None if handoff in ("", NO_HANDOFF) else handoff, count)
    return rows


def render(rows):
    """The whole file, every time. `map.md` is rewritten or not written at all."""
    lines = [
        "# smartcompact map",
        "",
        "Rewritten whole at every compaction boundary. A thread with no handoff is undecided.",
        "",
    ]
    if not rows:
        lines.append("_(no live threads tracked)_")
        return "\n".join(lines) + "\n"
    lines.append("| thread | handoff | attention |")
    lines.append("|---|---|---|")
    for name in sorted(rows):
        handoff, attention = rows[name]
        lines.append(f"| {name} | {handoff or NO_HANDOFF} | {attention} |")
    return "\n".join(lines) + "\n"


def thread_from_handoff_name(filename):
    """The thread in `hnd.<thread>--<datetime>.md`.

    Falls back to the whole stem when the separator is absent, because a
    handoff written by hand is still a handoff and losing it would be worse
    than filing it under an odd name.
    """
    stem = filename
    if stem.startswith(HANDOFF_PREFIX):
        stem = stem[len(HANDOFF_PREFIX) :]
    if stem.endswith(HANDOFF_SUFFIX):
        stem = stem[: -len(HANDOFF_SUFFIX)]
    thread, _, _stamp = stem.rpartition("--")
    return thread or stem
