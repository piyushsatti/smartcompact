"""state.py: the one path resolver, and the two ways anything here writes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import state


class TestDataDir(unittest.TestCase):
    def test_uses_claude_plugin_data_when_set(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/somewhere"}):
            self.assertEqual(state.data_dir(), Path("/tmp/somewhere"))

    def test_falls_back_when_unset(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            expected = Path(os.path.expanduser("~/.claude/plugins/data/smartcompact/"))
            self.assertEqual(state.data_dir(), expected)

    def test_falls_back_when_env_var_is_empty_string(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": ""}):
            expected = Path(os.path.expanduser("~/.claude/plugins/data/smartcompact/"))
            self.assertEqual(state.data_dir(), expected)


class TestProjectDir(unittest.TestCase):
    def test_lives_under_projects_subdir_of_data_dir(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            result = state.project_dir("/Users/pi/my-project")
        self.assertEqual(result.parent.parent, Path("/tmp/plugin-data"))
        self.assertEqual(result.parent.name, "projects")

    def test_two_different_paths_produce_two_different_keys(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            first = state.project_dir("/Users/pi/project-a")
            second = state.project_dir("/Users/pi/project-b")
        self.assertNotEqual(first, second)

    def test_same_path_produces_same_key_every_time(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            first = state.project_dir("/Users/pi/same-project")
            second = state.project_dir("/Users/pi/same-project")
        self.assertEqual(first, second)

    def test_slug_is_lowercase_hyphenated_no_leading_or_trailing_hyphen(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            result = state.project_dir("/Users/Pi Satti/My Project!!")
        slug = result.name
        self.assertEqual(slug, slug.lower())
        self.assertFalse(slug.startswith("-"))
        self.assertFalse(slug.endswith("-"))
        self.assertNotIn("--", slug)

    def test_none_cwd_does_not_raise(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            result = state.project_dir(None)
        self.assertIsInstance(result, Path)

    def test_empty_string_cwd_does_not_raise(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/plugin-data"}):
            result = state.project_dir("")
        self.assertIsInstance(result, Path)


class TestWriteAtomic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_writes_content_and_returns_true(self):
        target = Path(self.tmpdir.name) / "out.txt"
        ok = state.write_atomic(target, "hello world")
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "hello world")

    def test_creates_parent_directories(self):
        target = Path(self.tmpdir.name) / "a" / "b" / "c" / "out.txt"
        ok = state.write_atomic(target, "nested")
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "nested")

    def test_overwrites_existing_content(self):
        target = Path(self.tmpdir.name) / "out.txt"
        state.write_atomic(target, "first")
        ok = state.write_atomic(target, "second")
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "second")

    def test_leaves_no_temp_file_on_success(self):
        target = Path(self.tmpdir.name) / "out.txt"
        state.write_atomic(target, "content")
        leftovers = [p for p in Path(self.tmpdir.name).iterdir() if p != target]
        self.assertEqual(leftovers, [])

    def test_no_partial_file_when_content_write_fails(self):
        # bytes into a text-mode handle raises TypeError partway through the
        # write. write_atomic must catch it, return False, and leave nothing
        # behind: no destination file, no orphaned temp file.
        target = Path(self.tmpdir.name) / "out.txt"
        ok = state.write_atomic(target, b"not a string")
        self.assertFalse(ok)
        self.assertFalse(target.exists())
        self.assertEqual(list(Path(self.tmpdir.name).iterdir()), [])

    def test_existing_content_untouched_when_a_later_write_fails(self):
        target = Path(self.tmpdir.name) / "out.txt"
        state.write_atomic(target, "original")
        ok = state.write_atomic(target, b"not a string")
        self.assertFalse(ok)
        self.assertEqual(target.read_text(), "original")

    def test_does_not_raise_when_parent_cannot_be_created(self):
        # A plain file sitting where a directory component is expected makes
        # mkdir(parents=True) raise NotADirectoryError. write_atomic must
        # swallow it and report failure, not propagate it.
        blocker = Path(self.tmpdir.name) / "blocker"
        blocker.write_text("i am a file, not a directory")
        target = blocker / "sub" / "out.txt"
        ok = state.write_atomic(target, "content")
        self.assertFalse(ok)


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_appends_single_line_and_returns_true(self):
        target = Path(self.tmpdir.name) / "log.txt"
        ok = state.append(target, "one line\n")
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "one line\n")

    def test_creates_parent_directories(self):
        target = Path(self.tmpdir.name) / "a" / "b" / "log.txt"
        ok = state.append(target, "line\n")
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "line\n")

    def test_multiple_appends_accumulate_in_order(self):
        target = Path(self.tmpdir.name) / "log.txt"
        state.append(target, "first\n")
        state.append(target, "second\n")
        state.append(target, "third\n")
        self.assertEqual(target.read_text(), "first\nsecond\nthird\n")

    def test_does_not_raise_when_parent_cannot_be_created(self):
        blocker = Path(self.tmpdir.name) / "blocker"
        blocker.write_text("i am a file, not a directory")
        target = blocker / "sub" / "log.txt"
        ok = state.append(target, "line\n")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
