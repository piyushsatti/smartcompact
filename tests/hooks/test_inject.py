"""inject.py: only ever acts on source "compact", and only ever emits paths.

Drives the real script as a subprocess, the way Claude Code actually invokes
a hook, and asserts on its stdout and exit code. CLAUDE_PLUGIN_DATA is
redirected into a tempdir so no run here can touch real plugin data.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "inject.py"
SESSION_ID = "22222222-2222-2222-2222-222222222222"


def _slug(text):
    """Mirrors hooks/lib/state.py's _slug. Needed only to place fixtures at
    the same path project_dir() will independently resolve."""
    collapsed = re.sub(r"[^A-Za-z0-9]+", "-", str(text)) if text else ""
    return collapsed.strip("-").lower() or "unknown"


class InjectHookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved once, here: macOS mounts /tmp's tempdir root through a
        # symlink, and subprocess.run(cwd=...) chdir's the child past it, so
        # the child's own os.getcwd() would otherwise disagree with the
        # unresolved string this test hands the hook as payload["cwd"].
        tmp_root = Path(self.tmp.name).resolve()
        self.data_dir = tmp_root / "data"
        self.project_dir = tmp_root / "project"
        self.project_dir.mkdir()
        self.project_key_dir = self.data_dir / "projects" / _slug(str(self.project_dir))

    def env(self):
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data_dir)
        return env

    def payload(self, **overrides):
        base = {
            "source": "compact",
            "session_id": SESSION_ID,
            "cwd": str(self.project_dir),
            "model": "claude-test",
        }
        base.update(overrides)
        return base

    def run_hook(self, stdin_text):
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=stdin_text,
            cwd=str(self.project_dir),
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def run_hook_json(self, payload):
        return self.run_hook(json.dumps(payload))

    def write_map(self, text):
        self.project_key_dir.mkdir(parents=True, exist_ok=True)
        (self.project_key_dir / "map.md").write_text(text)

    def write_handoff(self, thread, datetime_suffix, body=""):
        self.project_key_dir.mkdir(parents=True, exist_ok=True)
        name = f"hnd.{thread}--{datetime_suffix}.md"
        (self.project_key_dir / name).write_text(body or f"handoff body for {thread}")
        return name

    def additional_context(self, result):
        parsed = json.loads(result.stdout)
        return parsed["hookSpecificOutput"]["additionalContext"]


class TestMalformedInput(InjectHookTestCase):
    def test_empty_stdin_exits_zero_and_prints_nothing(self):
        result = self.run_hook("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_json_exits_zero_and_prints_nothing(self):
        result = self.run_hook("{not valid json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_cwd_exits_zero_and_prints_nothing(self):
        payload = self.payload()
        del payload["cwd"]
        result = self.run_hook_json(payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_absent_transcript_path_field_is_harmless(self):
        # inject.py never reads transcript_path at all; a payload missing it
        # (the real shape SessionStart sends) must behave exactly as normal.
        self.write_map("| thread | handoff | attention |\n|---|---|---|\n")
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)


class TestSourceGate(InjectHookTestCase):
    def test_non_compact_sources_stay_silent_even_with_state_present(self):
        self.write_handoff("alpha", "20260101T000000Z")
        for source in ("startup", "resume", "clear", "fork"):
            with self.subTest(source=source):
                result = self.run_hook_json(self.payload(source=source))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_compact_with_state_present_emits(self):
        self.write_handoff("alpha", "20260101T000000Z")
        result = self.run_hook_json(self.payload(source="compact"))
        self.assertEqual(result.returncode, 0)
        self.assertNotEqual(result.stdout, "")


class TestNoState(InjectHookTestCase):
    def test_project_directory_absent_is_silent(self):
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_project_directory_present_but_empty_is_silent(self):
        self.project_key_dir.mkdir(parents=True)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestReferencesNotContent(InjectHookTestCase):
    def test_emits_hookSpecificOutput_shape(self):
        self.write_map("| thread | handoff | attention |\n|---|---|---|\n| alpha | (none) | 0 |\n")
        result = self.run_hook_json(self.payload())
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", parsed["hookSpecificOutput"])

    def test_references_map_path_and_never_a_handoffs_body_text(self):
        handoff_name = self.write_handoff("alpha", "20260101T000000Z", body="SECRET_ONLY_ON_DISK_42")
        self.write_map(f"| thread | handoff | attention |\n|---|---|---|\n| alpha | {handoff_name} | 2 |\n")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertIn(str(self.project_key_dir / "map.md"), context)
        self.assertIn(str(self.project_key_dir / handoff_name), context)
        self.assertIn("alpha", context)
        self.assertNotIn("SECRET_ONLY_ON_DISK_42", context)

    def test_names_undecided_threads(self):
        self.write_map(
            "| thread | handoff | attention |\n"
            "|---|---|---|\n"
            "| alpha | hnd.alpha--20260101T000000Z.md | 1 |\n"
            "| beta | (none) | 0 |\n"
        )
        self.write_handoff("alpha", "20260101T000000Z")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertIn("beta", context)
        undecided_line = next(line for line in context.splitlines() if "Undecided" in line)
        self.assertIn("beta", undecided_line)
        self.assertNotIn("alpha", undecided_line)

    def test_map_missing_but_handoffs_present_still_emits(self):
        self.write_handoff("alpha", "20260101T000000Z")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertIn("no resident map", context)
        self.assertIn("alpha", context)

    def test_empty_map_says_so_rather_than_pretending(self):
        self.write_map("")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertIn(str(self.project_key_dir / "map.md"), context)
        self.assertIn("empty", context.lower())


class TestSizeCap(InjectHookTestCase):
    def test_stays_under_cap_and_says_it_truncated(self):
        for i in range(200):
            self.write_handoff(f"t{i:04d}", "20260101T000000Z")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertLessEqual(len(context), 10_000)
        self.assertIn("truncated", context)
        self.assertIn("t0199", context)  # newest: must survive
        self.assertNotIn("t0000", context)  # oldest: dropped first

    def test_no_truncation_note_when_comfortably_under_cap(self):
        self.write_handoff("alpha", "20260101T000000Z")
        result = self.run_hook_json(self.payload())
        context = self.additional_context(result)
        self.assertNotIn("truncated", context)


if __name__ == "__main__":
    unittest.main()
