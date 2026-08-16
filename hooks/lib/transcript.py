"""Read the tail of a Claude Code transcript. Never the whole file.

Transcripts are JSONL, one record per line, appended to for the life of a
session, and reach 150 MB by the end of a long one. This module is imported
by a hook that runs at the end of every turn, so its own cost has to track
the size of the last few messages, not the size of the whole session.
"""

import json
import os

# Where the backward walk starts. 64 KB comfortably holds several assistant
# messages' worth of JSON, so most calls need exactly one read.
INITIAL_CHUNK = 64 * 1024

# Doubled on each retry that finds nothing, capped here. A transcript with no
# assistant record in its last few megabytes is not one this function can
# afford to keep searching; give up and let the caller treat that the same
# as "not found."
MAX_READ = 4 * 1024 * 1024


def last_usage(path):
    """The usage dict off the last assistant message in path, or None.

    None covers every failure alike: a missing file, an empty one, a final
    line half-written by an append still in progress, no assistant record at
    all, and an assistant record with no usage key. A caller cannot tell
    these apart from here and does not need to; occupancy reads as zero
    either way.
    """
    try:
        size = os.path.getsize(path)
        if size <= 0:
            return None
        with open(path, "rb") as handle:
            read_size = min(INITIAL_CHUNK, size)
            while True:
                handle.seek(size - read_size)
                record = _last_assistant_record(handle.read(read_size))
                if record is not None:
                    message = record.get("message")
                    return message.get("usage") if isinstance(message, dict) else None
                if read_size >= size or read_size >= MAX_READ:
                    return None
                read_size = min(read_size * 2, size, MAX_READ)
    except Exception:
        # Permission denied, a directory instead of a file, an undecodable
        # byte: all of it means "no usage available," never a crash.
        return None


def _last_assistant_record(blob):
    """The most recent complete, parseable assistant record inside blob."""
    for line in reversed(blob.split(b"\n")):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            # blob's own edges can land inside a line, and a transcript's
            # true last line is routinely half-written mid-append. Both look
            # identical from here: skip it and keep walking backward.
            continue
        if isinstance(record, dict) and record.get("type") == "assistant":
            return record
    return None
