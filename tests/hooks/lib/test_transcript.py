"""transcript.py: last_usage must find the last assistant record from the
tail of the file, without reading the whole thing, and must never raise."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import transcript


def _assistant(usage):
    """A record.get("type") == "assistant" line with the given usage dict."""
    return {"type": "assistant", "message": {"usage": usage}}


def _assistant_without_usage_key():
    return {"type": "assistant", "message": {"role": "assistant"}}


def _user(padding=""):
    return {"type": "user", "message": {"role": "user", "content": padding}}


def _jsonl(records, trailing_newline=True):
    body = "\n".join(json.dumps(r) for r in records)
    return body + "\n" if trailing_newline else body


class TranscriptTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "transcript.jsonl"

    def write(self, text, mode="w"):
        with open(self.path, mode) as handle:
            handle.write(text)


class TestMissingAndEmpty(TranscriptTestCase):
    def test_missing_file_returns_none(self):
        missing = Path(self.tmpdir.name) / "does-not-exist.jsonl"
        self.assertIsNone(transcript.last_usage(missing))

    def test_empty_file_returns_none(self):
        self.write("")
        self.assertIsNone(transcript.last_usage(self.path))

    def test_directory_instead_of_file_does_not_raise(self):
        directory = Path(self.tmpdir.name) / "a-directory"
        directory.mkdir()
        self.assertIsNone(transcript.last_usage(directory))


class TestTruncation(TranscriptTestCase):
    def test_truncated_only_line_returns_none(self):
        # The normal state of a transcript being appended to right now: the
        # final line is half a JSON object, with no newline after it.
        self.write('{"type": "assistant", "message": {"usage": {"inp')
        self.assertIsNone(transcript.last_usage(self.path))

    def test_truncated_trailing_line_falls_back_to_last_complete_record(self):
        usage = {"input_tokens": 111, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0}
        complete = _jsonl([_assistant(usage)], trailing_newline=True)
        self.write(complete + '{"type": "assistant", "message": {"usage": {"inp')
        self.assertEqual(transcript.last_usage(self.path), usage)


class TestUsagePresence(TranscriptTestCase):
    def test_last_assistant_message_without_usage_returns_none(self):
        earlier_usage = {"input_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        records = [_assistant(earlier_usage), _assistant_without_usage_key()]
        self.write(_jsonl(records))
        # Must NOT fall back to the earlier record that did have usage.
        self.assertIsNone(transcript.last_usage(self.path))

    def test_finds_usage_of_the_last_of_several_assistant_messages(self):
        first = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        second = {"input_tokens": 2, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        third = {"input_tokens": 3, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.write(_jsonl([_assistant(first), _assistant(second), _assistant(third)]))
        self.assertEqual(transcript.last_usage(self.path), third)

    def test_ignores_non_assistant_records_after_the_last_assistant_message(self):
        usage = {"input_tokens": 42, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0}
        records = [_assistant(usage), _user("a tool result or user turn")]
        self.write(_jsonl(records))
        self.assertEqual(transcript.last_usage(self.path), usage)

    def test_no_assistant_record_anywhere_returns_none(self):
        self.write(_jsonl([_user("hi"), _user("only user turns here")]))
        self.assertIsNone(transcript.last_usage(self.path))

    def test_malformed_non_json_lines_are_skipped_without_raising(self):
        usage = {"input_tokens": 7, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = ["not json at all", json.dumps(_assistant(usage)), "{also not valid json"]
        self.write("\n".join(lines) + "\n")
        self.assertEqual(transcript.last_usage(self.path), usage)


class TestTailReadAtRealScale(TranscriptTestCase):
    def test_finds_target_beyond_the_initial_64kb_chunk(self):
        # Padding placed AFTER the target pushes it more than INITIAL_CHUNK
        # bytes from EOF, so the first backward read must miss it and the
        # function must grow its window to find it at all.
        usage = {"input_tokens": 999, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 1}
        padding_line = json.dumps(_user("x" * 600))
        padding_bytes_needed = transcript.INITIAL_CHUNK + 20_000
        pad_count = (padding_bytes_needed // (len(padding_line) + 1)) + 1
        records_text = json.dumps(_assistant(usage)) + "\n"
        records_text += "\n".join(padding_line for _ in range(pad_count)) + "\n"
        self.write(records_text)
        self.assertGreater(self.path.stat().st_size, transcript.INITIAL_CHUNK)
        self.assertEqual(transcript.last_usage(self.path), usage)


class TestTailReadGrowthAndCap(TranscriptTestCase):
    def test_grows_the_window_until_the_record_is_found(self):
        usage = {"input_tokens": 55, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        padding_line = json.dumps(_user("y" * 40))
        # Padding total comfortably exceeds the patched 64-byte starting
        # chunk, so finding the record at all requires several doublings.
        text = json.dumps(_assistant(usage)) + "\n"
        text += "\n".join(padding_line for _ in range(12)) + "\n"
        self.write(text)
        with (
            mock.patch.object(transcript, "INITIAL_CHUNK", 64),
            mock.patch.object(transcript, "MAX_READ", 100_000),
        ):
            self.assertEqual(transcript.last_usage(self.path), usage)

    def test_gives_up_once_max_read_is_exceeded(self):
        usage = {"input_tokens": 55, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        padding_line = json.dumps(_user("z" * 200))
        text = json.dumps(_assistant(usage)) + "\n"
        text += "\n".join(padding_line for _ in range(20)) + "\n"
        self.write(text)
        self.assertGreater(self.path.stat().st_size, 300)
        with (
            mock.patch.object(transcript, "INITIAL_CHUNK", 32),
            mock.patch.object(transcript, "MAX_READ", 128),
        ):
            # The record sits well past what a 128-byte cap can ever reach,
            # even though a full read of this small file would find it.
            self.assertIsNone(transcript.last_usage(self.path))


class TestDoesNotRaise(TranscriptTestCase):
    def test_unreadable_file_permission_denied_does_not_raise(self):
        self.write(_jsonl([_assistant({"input_tokens": 1})]))
        os.chmod(self.path, 0o000)
        try:
            result = transcript.last_usage(self.path)
        finally:
            os.chmod(self.path, 0o644)  # restore so TemporaryDirectory cleanup can remove it
        # Running as root ignores permission bits, so this only asserts
        # "did not raise" rather than a specific None, which root would fail.
        self.assertIn(result, (None, {"input_tokens": 1}))


if __name__ == "__main__":
    unittest.main()
