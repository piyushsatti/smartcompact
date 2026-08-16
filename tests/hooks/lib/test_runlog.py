"""runlog.py: one formatted line per call, rotated at 1 MB, never raising."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import runlog


class RunlogTestCase(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)

        env_patcher = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.data_dir.name})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        cwd_patcher = mock.patch("os.getcwd", return_value="/fake/project/for-runlog-tests")
        cwd_patcher.start()
        self.addCleanup(cwd_patcher.stop)

        self.log_path = Path(self.data_dir.name) / "projects" / "fake-project-for-runlog-tests" / "run.log"


class TestRecordFormat(RunlogTestCase):
    def test_returns_true_on_success(self):
        self.assertTrue(runlog.record("turn-end", "soft"))

    def test_appends_event_and_outcome(self):
        runlog.record("turn-end", "soft")
        line = self.log_path.read_text().strip()
        self.assertTrue(line.endswith("turn-end soft"), line)

    def test_includes_ms_when_given(self):
        runlog.record("turn-end", "soft", ms=42)
        line = self.log_path.read_text().strip()
        self.assertTrue(line.endswith("turn-end soft 42ms"), line)

    def test_includes_detail_when_given(self):
        runlog.record("turn-end", "soft", detail="advisory shown")
        line = self.log_path.read_text().strip()
        self.assertTrue(line.endswith("turn-end soft advisory shown"), line)

    def test_includes_both_ms_and_detail_in_order(self):
        runlog.record("turn-end", "hard", ms=7, detail="blocked")
        line = self.log_path.read_text().strip()
        self.assertTrue(line.endswith("turn-end hard 7ms blocked"), line)

    def test_omits_ms_and_detail_fields_entirely_when_absent(self):
        runlog.record("session-end", "ok")
        line = self.log_path.read_text().strip()
        self.assertNotIn("ms", line)
        self.assertEqual(len(line.split(" ")), 3)  # timestamp, event, outcome only

    def test_timestamp_is_iso8601_utc(self):
        runlog.record("turn-end", "soft")
        line = self.log_path.read_text().strip()
        stamp = line.split(" ")[0]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_each_call_appends_a_new_line(self):
        runlog.record("a", "1")
        runlog.record("b", "2")
        lines = self.log_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("a 1"))
        self.assertTrue(lines[1].endswith("b 2"))


class TestRotation(RunlogTestCase):
    def test_rotates_when_over_max_size(self):
        self.log_path.parent.mkdir(parents=True)
        self.log_path.write_text("x" * 200 + "\n")
        with mock.patch.object(runlog, "MAX_SIZE", 100):
            runlog.record("turn-end", "soft")
        rotated = self.log_path.with_name("run.log.1")
        self.assertTrue(rotated.exists())
        self.assertIn("x" * 200, rotated.read_text())

    def test_fresh_log_after_rotation_holds_only_the_new_line(self):
        self.log_path.parent.mkdir(parents=True)
        self.log_path.write_text("x" * 200 + "\n")
        with mock.patch.object(runlog, "MAX_SIZE", 100):
            runlog.record("turn-end", "soft")
        line = self.log_path.read_text().strip()
        self.assertTrue(line.endswith("turn-end soft"))
        self.assertNotIn("x" * 200, line)

    def test_rotation_replaces_an_existing_generation_one(self):
        self.log_path.parent.mkdir(parents=True)
        rotated = self.log_path.with_name("run.log.1")
        rotated.write_text("stale generation from a previous rotation\n")
        self.log_path.write_text("y" * 200 + "\n")
        with mock.patch.object(runlog, "MAX_SIZE", 100):
            runlog.record("turn-end", "soft")
        content = rotated.read_text()
        self.assertNotIn("stale generation", content)
        self.assertIn("y" * 200, content)

    def test_stays_under_max_size_does_not_rotate(self):
        self.log_path.parent.mkdir(parents=True)
        self.log_path.write_text("short\n")
        with mock.patch.object(runlog, "MAX_SIZE", 1024 * 1024):
            runlog.record("turn-end", "soft")
        self.assertFalse(self.log_path.with_name("run.log.1").exists())


class TestDoesNotRaise(RunlogTestCase):
    def test_returns_false_when_cwd_is_unavailable(self):
        with mock.patch("os.getcwd", side_effect=FileNotFoundError("cwd was deleted")):
            self.assertFalse(runlog.record("turn-end", "soft"))

    def test_returns_false_when_project_dir_cannot_be_created(self):
        # A plain file sitting at the "projects" path component makes mkdir
        # raise NotADirectoryError deep inside state.append.
        blocker = Path(self.data_dir.name) / "projects"
        blocker.write_text("i am a file, not a directory")
        self.assertFalse(runlog.record("turn-end", "soft"))


if __name__ == "__main__":
    unittest.main()
