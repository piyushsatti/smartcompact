"""zone.py: speaks at most once per rise, keyed by session, and never crashes.

Drives the real script as a subprocess, the way Claude Code actually invokes
a hook, and asserts on its stdout and exit code. CLAUDE_PLUGIN_DATA and HOME
are both redirected into a tempdir so no run here can touch a real ~/.claude
or real plugin data.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "zone.py"
SESSION_ID = "11111111-1111-1111-1111-111111111111"


def _slug(text):
    """Mirrors hooks/lib/state.py's _slug. Needed only to find fixtures at the
    same path the hook itself will independently resolve."""
    collapsed = re.sub(r"[^A-Za-z0-9]+", "-", str(text)) if text else ""
    return collapsed.strip("-").lower() or "unknown"


def _usage(total):
    return {"input_tokens": total, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _assistant_line(usage):
    return json.dumps({"type": "assistant", "message": {"usage": usage}}) + "\n"


class ZoneHookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved once, here: macOS mounts /tmp's tempdir root through a
        # symlink, and subprocess.run(cwd=...) chdir's the child past it, so
        # the child's own os.getcwd() (which runlog.record reads) would
        # otherwise disagree with the unresolved string this test hands the
        # hook as payload["cwd"]. Resolving up front keeps both sides equal.
        tmp_root = Path(self.tmp.name).resolve()
        self.data_dir = tmp_root / "data"
        self.home_dir = tmp_root / "home"
        self.home_dir.mkdir()
        self.project_dir = tmp_root / "project"
        self.project_dir.mkdir()
        self.transcript_path = tmp_root / "transcript.jsonl"

    def env(self):
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data_dir)
        env["HOME"] = str(self.home_dir)
        return env

    def write_settings(self, window):
        settings_dir = self.home_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(json.dumps({"autoCompactWindow": window}))

    def write_transcript(self, usage):
        self.transcript_path.write_text(_assistant_line(usage))

    def payload(self, **overrides):
        base = {
            "session_id": SESSION_ID,
            "transcript_path": str(self.transcript_path),
            "cwd": str(self.project_dir),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
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

    def latch_path(self):
        return self.data_dir / "projects" / _slug(str(self.project_dir)) / "zone" / SESSION_ID


class TestMalformedInput(ZoneHookTestCase):
    def test_empty_stdin_exits_zero_and_prints_nothing(self):
        result = self.run_hook("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_json_exits_zero_and_prints_nothing(self):
        result = self.run_hook("{not valid json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_path_exits_zero_and_prints_nothing(self):
        payload = self.payload()
        del payload["transcript_path"]
        result = self.run_hook_json(payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_transcript_with_only_a_truncated_line_prints_nothing(self):
        self.transcript_path.write_text('{"type": "assistant", "message": {"usage": {"inp')
        self.write_settings(300_000)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_file_prints_nothing(self):
        missing = Path(self.tmp.name) / "does-not-exist.jsonl"
        self.write_settings(300_000)
        result = self.run_hook_json(self.payload(transcript_path=str(missing)))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestSilentConditions(ZoneHookTestCase):
    def test_zero_occupancy_prints_nothing(self):
        self.write_transcript(_usage(0))
        self.write_settings(300_000)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_unresolved_trigger_prints_nothing(self):
        # No settings.json at all under the redirected HOME: auto_compact_window()
        # returns None, trigger_point(None) is None, zone() is unanchored.
        self.write_transcript(_usage(200_000))
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.latch_path().exists())

    def test_first_measurement_this_session_seeds_the_latch_but_says_nothing(self):
        # trigger = 300,000 - 33,400 = 266,600. soft edge 159,960, hard edge
        # 213,280. 180,000 lands orange, which would be a rise out of an
        # unseeded latch, and the hook must still stay silent: there is no
        # prior turn to be rising past.
        self.write_settings(300_000)
        self.write_transcript(_usage(180_000))
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.latch_path().read_text().strip(), "orange")

    def test_invalid_session_id_is_ignored_rather_than_used_as_a_path(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(250_000))
        result = self.run_hook_json(self.payload(session_id="../../escape"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.data_dir / "projects").exists())


class TestDebounce(ZoneHookTestCase):
    def setUp(self):
        super().setUp()
        self.write_settings(300_000)  # trigger 266,600; soft 159,960; hard 213,280

    def speak(self, total):
        self.write_transcript(_usage(total))
        return self.run_hook_json(self.payload())

    def test_speaks_once_on_a_rise_and_not_again_for_the_same_zone(self):
        seed = self.speak(50_000)  # green: first measurement, seeds silently
        self.assertEqual(seed.stdout, "")

        rise = self.speak(180_000)  # orange: a rise past the seeded green latch
        self.assertEqual(rise.returncode, 0)
        message = json.loads(rise.stdout)["systemMessage"]
        self.assertIn("orange", message)

        same = self.speak(190_000)  # still orange: no second announcement
        self.assertEqual(same.stdout, "")

    def test_speaks_again_after_the_zone_falls_and_rises_anew(self):
        self.speak(50_000)  # green, seeds silently
        first_rise = self.speak(250_000)  # red: rise
        self.assertIn("red", json.loads(first_rise.stdout)["systemMessage"])

        fall = self.speak(50_000)  # back to green: silent, but resets the latch
        self.assertEqual(fall.stdout, "")
        self.assertEqual(self.latch_path().read_text().strip(), "green")

        second_rise = self.speak(180_000)  # orange again: a fresh rise, must speak
        self.assertIn("orange", json.loads(second_rise.stdout)["systemMessage"])

    def test_falling_from_hard_to_soft_stays_silent(self):
        self.speak(50_000)  # green seed
        self.speak(250_000)  # red, spoken
        fall = self.speak(180_000)  # orange: still a fall from red, must stay silent
        self.assertEqual(fall.stdout, "")
        self.assertEqual(self.latch_path().read_text().strip(), "orange")


class TestMessageFormat(ZoneHookTestCase):
    def test_message_is_one_json_object_with_systemMessage_key(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(50_000))
        self.run_hook_json(self.payload())  # seed
        self.write_transcript(_usage(180_000))  # rise
        result = self.run_hook_json(self.payload())

        lines = result.stdout.strip("\n").splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(set(parsed), {"systemMessage"})
        self.assertIsInstance(parsed["systemMessage"], str)
        self.assertIn("orange", parsed["systemMessage"])
        self.assertIn("180,000", parsed["systemMessage"])


if __name__ == "__main__":
    unittest.main()
