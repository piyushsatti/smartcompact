"""materialise.py: records every boundary, never blocks, and never writes a decided disposition.

Drives the real script as a subprocess, the way Claude Code actually invokes a hook, exactly like
zone.py's and inject.py's own test files. The one thing this hook does that those three do
not is spawn a second subprocess of its own, the sub-agent that runs the ritual's judgement steps; a
real `claude` is never invoked here. SMARTCOMPACT_CLAUDE_BIN points that spawn at a small stub script
instead, and CLAUDE_PLUGIN_DATA and HOME are both redirected into a tempdir so no run here can touch
real plugin data or a real settings.json.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "materialise.py"
SESSION_ID = "44444444-4444-4444-4444-444444444444"

# One configurable stub standing in for `claude -p`, controlled entirely by
# environment variables so a single script file serves every scenario below
# without being regenerated per test. Always drains stdin first, whether or
# not anything reads the capture, so materialise.py's own write never blocks
# on a pipe nobody is emptying.
STUB_SOURCE = """#!/usr/bin/env python3
import os
import sys
import time

prompt = sys.stdin.read()

capture = os.environ.get("SMARTCOMPACT_TEST_STDIN_CAPTURE")
if capture:
    with open(capture, "w", encoding="utf-8") as handle:
        handle.write(prompt)

mark = os.environ.get("SMARTCOMPACT_TEST_MARK")
if mark:
    open(mark, "w").close()

sleep_s = float(os.environ.get("SMARTCOMPACT_TEST_SLEEP_S") or "0")
if sleep_s:
    time.sleep(sleep_s)

exit_code = int(os.environ.get("SMARTCOMPACT_TEST_EXIT_CODE") or "1")
response_file = os.environ.get("SMARTCOMPACT_TEST_RESPONSE_FILE")
if response_file and os.path.isfile(response_file) and exit_code == 0:
    sys.stdout.write(open(response_file, encoding="utf-8").read())
sys.exit(exit_code)
"""


def _slug(text):
    """Mirrors hooks/lib/state.py's own _slug. Needed only to find fixtures at
    the same path the hook itself will independently resolve."""
    collapsed = re.sub(r"[^A-Za-z0-9]+", "-", str(text)) if text else ""
    return collapsed.strip("-").lower() or "unknown"


def _usage(total):
    return {"input_tokens": total, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class MaterialiseHookTestCase(unittest.TestCase):
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
        self.project_key_dir = self.data_dir / "projects" / _slug(str(self.project_dir))

        self.stub_path = tmp_root / "claude_stub.py"
        self.stub_path.write_text(STUB_SOURCE)
        self.stub_path.chmod(0o755)
        self.mark_path = tmp_root / "invoked.marker"
        self.response_path = tmp_root / "response.json"
        self.stdin_capture_path = tmp_root / "stdin.captured"

        # Fails immediately unless a test calls configure_stub: the safe
        # default for every test that is not itself about the sub-agent's
        # response, so a forgotten override can never shell out to a real
        # `claude` and can never hang waiting on one either.
        self.extra_env = {
            "SMARTCOMPACT_CLAUDE_BIN": str(self.stub_path),
            "SMARTCOMPACT_SUBPROCESS_TIMEOUT_S": "5",
            "SMARTCOMPACT_TEST_MARK": str(self.mark_path),
            "SMARTCOMPACT_TEST_EXIT_CODE": "1",
        }

    def configure_stub(self, *, exit_code=None, sleep_s=None, response=None, capture_stdin=False):
        if exit_code is not None:
            self.extra_env["SMARTCOMPACT_TEST_EXIT_CODE"] = str(exit_code)
        if sleep_s is not None:
            self.extra_env["SMARTCOMPACT_TEST_SLEEP_S"] = str(sleep_s)
        if response is not None:
            self.response_path.write_text(response)
            self.extra_env["SMARTCOMPACT_TEST_RESPONSE_FILE"] = str(self.response_path)
        if capture_stdin:
            self.extra_env["SMARTCOMPACT_TEST_STDIN_CAPTURE"] = str(self.stdin_capture_path)

    def env(self):
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data_dir)
        env["HOME"] = str(self.home_dir)
        env.update(self.extra_env)
        return env

    def write_settings(self, window):
        settings_dir = self.home_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(json.dumps({"autoCompactWindow": window}))

    def write_transcript(self, usage):
        self.transcript_path.write_text(json.dumps({"type": "assistant", "message": {"usage": usage}}) + "\n")

    def write_map(self, text):
        self.project_key_dir.mkdir(parents=True, exist_ok=True)
        (self.project_key_dir / "map.md").write_text(text)

    def payload(self, **overrides):
        base = {
            "session_id": SESSION_ID,
            "transcript_path": str(self.transcript_path),
            "cwd": str(self.project_dir),
            "trigger": "auto",
            "custom_instructions": "",
            "hook_event_name": "PreCompact",
        }
        base.update(overrides)
        return base

    def run_hook(self, stdin_text, timeout=15):
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=stdin_text,
            cwd=str(self.project_dir),
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def run_hook_json(self, payload, timeout=15):
        return self.run_hook(json.dumps(payload), timeout=timeout)

    def boundaries_path(self):
        return self.project_key_dir / "boundaries.jsonl"

    def map_path(self):
        return self.project_key_dir / "map.md"

    def run_log_path(self):
        return self.project_key_dir / "run.log"

    def handoff_paths(self):
        if not self.project_key_dir.is_dir():
            return []
        return sorted(self.project_key_dir.glob("hnd.*.md"))


class TestMalformedInput(MaterialiseHookTestCase):
    def test_empty_stdin_exits_zero(self):
        result = self.run_hook("")
        self.assertEqual(result.returncode, 0)

    def test_malformed_json_exits_zero(self):
        result = self.run_hook("{not valid json")
        self.assertEqual(result.returncode, 0)

    def test_missing_cwd_exits_zero_and_writes_nothing(self):
        payload = self.payload()
        del payload["cwd"]
        result = self.run_hook_json(payload)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.data_dir.exists())

    def test_missing_transcript_path_field_exits_zero(self):
        payload = self.payload()
        del payload["transcript_path"]
        result = self.run_hook_json(payload)
        self.assertEqual(result.returncode, 0)

    def test_missing_transcript_file_exits_zero(self):
        missing = Path(self.tmp.name) / "does-not-exist.jsonl"
        result = self.run_hook_json(self.payload(transcript_path=str(missing)))
        self.assertEqual(result.returncode, 0)

    def test_transcript_truncated_mid_json_exits_zero(self):
        self.transcript_path.write_text('{"type": "assistant", "message": {"usage": {"inp')
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)


class TestBoundaryRecording(MaterialiseHookTestCase):
    def test_records_boundary_even_when_subagent_fails_entirely(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(180_000))
        result = self.run_hook_json(self.payload(trigger="auto"))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.boundaries_path().is_file())
        lines = self.boundaries_path().read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["trigger"], "auto")
        self.assertEqual(entry["session_id"], SESSION_ID)
        self.assertRegex(entry["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertIn("occupancy", entry)
        self.assertIn("zone", entry)

    def test_boundary_reports_zero_occupancy_when_transcript_path_absent(self):
        payload = self.payload()
        del payload["transcript_path"]
        result = self.run_hook_json(payload)
        self.assertEqual(result.returncode, 0)
        entry = json.loads(self.boundaries_path().read_text().strip().splitlines()[0])
        self.assertEqual(entry["occupancy"], 0)


class TestReentrancy(MaterialiseHookTestCase):
    def test_does_not_spawn_when_depth_already_set_and_still_writes_skeleton(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(50_000))
        self.extra_env["SMARTCOMPACT_DEPTH"] = "1"
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.mark_path.exists(), "the stub must never be invoked when depth is set")
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("unattended", handoffs[0].name)
        self.assertIn("undecided", handoffs[0].read_text())
        self.assertIn("reentrant", self.run_log_path().read_text())


class TestTimeout(MaterialiseHookTestCase):
    def test_writes_skeleton_on_subagent_timeout(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(50_000))
        self.extra_env["SMARTCOMPACT_SUBPROCESS_TIMEOUT_S"] = "1"
        self.configure_stub(exit_code=0, sleep_s=3, response=json.dumps({"threads": []}))
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("unattended", handoffs[0].name)
        self.assertIn("timed out", self.run_log_path().read_text())


class TestSuccessPath(MaterialiseHookTestCase):
    def test_writes_handoff_and_map_from_subagent_response(self):
        response = json.dumps(
            {
                "threads": [
                    {
                        "thread": "alpha",
                        "disposition": "continue",
                        "objective": "ship the materialiser",
                        "phase": "build",
                        "state": "handoff written",
                        "next_step": "run tests",
                        "pointers": ["hooks/materialise.py"],
                    }
                ]
            }
        )
        self.configure_stub(exit_code=0, response=response)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertTrue(handoffs[0].name.startswith("hnd.alpha--"))
        body = handoffs[0].read_text()
        self.assertIn("Disposition: continue (proposed, undecided)", body)
        self.assertIn("ship the materialiser", body)
        self.assertIn("hooks/materialise.py", body)
        map_text = self.map_path().read_text()
        self.assertIn("alpha", map_text)
        self.assertIn(handoffs[0].name, map_text)
        self.assertIn("ritual", self.run_log_path().read_text())

    def test_subagent_proposing_close_is_written_but_never_routed(self):
        # Nothing is parked, closed or escalated on the sub-agent's own
        # judgement: even a proposed "close" must land as an ordinary,
        # undecided handoff that stays live, never as an actual routing.
        response = json.dumps({"threads": [{"thread": "beta", "disposition": "close"}]})
        self.configure_stub(exit_code=0, response=response)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("Disposition: close (proposed, undecided)", handoffs[0].read_text())
        self.assertFalse((self.project_key_dir / "closed.md").exists())
        self.assertIn("beta", self.map_path().read_text())

    def test_empty_threads_list_is_success_not_fallback(self):
        self.configure_stub(exit_code=0, response=json.dumps({"threads": []}))
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.handoff_paths(), [])
        self.assertIn("no live threads", self.map_path().read_text())
        log_text = self.run_log_path().read_text()
        self.assertIn("ritual", log_text)
        self.assertNotIn("skeleton", log_text)

    def test_garbage_response_falls_back_to_skeleton(self):
        self.configure_stub(exit_code=0, response="not json at all, sorry")
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("unattended", handoffs[0].name)
        self.assertIn("nothing usable", self.run_log_path().read_text())

    def test_response_missing_threads_key_falls_back_to_skeleton(self):
        self.configure_stub(exit_code=0, response=json.dumps({"unexpected": "shape"}))
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self.handoff_paths()), 1)
        self.assertIn("nothing usable", self.run_log_path().read_text())

    def test_nonzero_exit_from_subagent_falls_back_to_skeleton(self):
        self.configure_stub(exit_code=7)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("unattended", handoffs[0].name)

    def test_response_fenced_and_wrapped_in_prose_is_still_parsed(self):
        wrapped = (
            "Here is the ritual's output, as requested.\n\n"
            "```json\n" + json.dumps({"threads": [{"thread": "gamma", "disposition": "fork"}]}) + "\n```\n"
            "That covers every open thread.\n"
        )
        self.configure_stub(exit_code=0, response=wrapped)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertTrue(handoffs[0].name.startswith("hnd.gamma--"))


class TestUndecidedDisposition(MaterialiseHookTestCase):
    def test_every_handoff_on_the_success_path_is_marked_undecided(self):
        response = json.dumps(
            {
                "threads": [
                    {"thread": "a", "disposition": "park"},
                    {"thread": "b", "disposition": "escalate"},
                    {"thread": "c", "disposition": "close"},
                ]
            }
        )
        self.configure_stub(exit_code=0, response=response)
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 3)
        for path in handoffs:
            self.assertIn("undecided", path.read_text())

    def test_fallback_skeleton_handoff_is_marked_undecided(self):
        result = self.run_hook_json(self.payload())  # default stub fails immediately
        self.assertEqual(result.returncode, 0)
        handoffs = self.handoff_paths()
        self.assertEqual(len(handoffs), 1)
        self.assertIn("undecided", handoffs[0].read_text())


class TestMapReconciliation(MaterialiseHookTestCase):
    def test_a_thread_the_subagent_did_not_mention_survives_untouched(self):
        self.write_map(
            "| thread | handoff | attention |\n"
            "|---|---|---|\n"
            "| old-thread | hnd.old-thread--20260101T000000Z.md | 3 |\n"
        )
        self.configure_stub(
            exit_code=0,
            response=json.dumps({"threads": [{"thread": "new-thread", "disposition": "continue"}]}),
        )
        result = self.run_hook_json(self.payload())
        self.assertEqual(result.returncode, 0)
        map_text = self.map_path().read_text()
        self.assertIn("| old-thread | hnd.old-thread--20260101T000000Z.md | 3 |", map_text)
        self.assertIn("new-thread", map_text)


class TestPromptWiring(MaterialiseHookTestCase):
    def test_prompt_carries_ritual_transcript_path_and_custom_instructions(self):
        self.configure_stub(exit_code=0, response=json.dumps({"threads": []}), capture_stdin=True)
        result = self.run_hook_json(
            self.payload(custom_instructions="focus the summary on the auth refactor")
        )
        self.assertEqual(result.returncode, 0)
        prompt = self.stdin_capture_path.read_text()
        self.assertIn("The compaction-boundary ritual", prompt)  # ritual.md's own title, not restated
        self.assertIn(str(self.transcript_path), prompt)
        self.assertIn("focus the summary on the auth refactor", prompt)
        self.assertIn("step 5 suppressed", prompt)


class TestNoTornOutput(MaterialiseHookTestCase):
    def test_killed_mid_run_leaves_no_torn_file_behind(self):
        self.write_settings(300_000)
        self.write_transcript(_usage(50_000))
        self.extra_env["SMARTCOMPACT_SUBPROCESS_TIMEOUT_S"] = "30"
        self.configure_stub(exit_code=0, sleep_s=3, response=json.dumps({"threads": []}))

        proc = subprocess.Popen(
            [sys.executable, str(HOOK)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.project_dir),
            env=self.env(),
            text=True,
        )
        try:
            proc.stdin.write(json.dumps(self.payload()))
            proc.stdin.close()
            # Long enough for the hook to log the boundary and spawn the
            # stub, well short of the stub's own 3-second sleep: the hook is
            # caught blocked inside subprocess.run, mid-run by construction.
            time.sleep(0.5)
            proc.kill()
            proc.wait(timeout=10)
        finally:
            proc.stdout.close()
            proc.stderr.close()

        if self.project_key_dir.is_dir():
            leftovers = [p for p in self.project_key_dir.rglob("*") if p.is_file() and ".tmp" in p.name]
            self.assertEqual(leftovers, [], f"torn temp file left behind: {leftovers}")
            if self.boundaries_path().exists():
                for line in self.boundaries_path().read_text().splitlines():
                    json.loads(line)  # raises ValueError if this line was torn mid-write
            for handoff in self.handoff_paths():
                self.assertIn("Disposition:", handoff.read_text())


if __name__ == "__main__":
    unittest.main()
