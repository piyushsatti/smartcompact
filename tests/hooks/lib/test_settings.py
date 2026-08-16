"""settings.py: read-only autoCompactWindow, and a validated threshold override."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import occupancy, settings


class TestAutoCompactWindow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.settings_path = Path(self.tmpdir.name) / "settings.json"
        patcher = mock.patch.object(settings, "_settings_path", return_value=self.settings_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_value_when_present_and_numeric(self):
        self.settings_path.write_text('{"autoCompactWindow": 250000}')
        self.assertEqual(settings.auto_compact_window(), 250000)

    def test_returns_none_when_file_missing(self):
        self.assertIsNone(settings.auto_compact_window())

    def test_returns_none_when_json_is_invalid(self):
        self.settings_path.write_text("{not valid json")
        self.assertIsNone(settings.auto_compact_window())

    def test_returns_none_when_key_absent(self):
        self.settings_path.write_text('{"someOtherKey": true}')
        self.assertIsNone(settings.auto_compact_window())

    def test_returns_none_when_value_is_not_numeric(self):
        self.settings_path.write_text('{"autoCompactWindow": "a lot"}')
        self.assertIsNone(settings.auto_compact_window())

    def test_returns_none_when_top_level_is_not_an_object(self):
        self.settings_path.write_text("[1, 2, 3]")
        self.assertIsNone(settings.auto_compact_window())


class ThresholdsTestCase(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        self.override_path = Path(self.data_dir.name) / "smartcompact.yaml"

        env_patcher = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.data_dir.name})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        cwd_patcher = mock.patch("os.getcwd", return_value="/fake/project/for-thresholds-tests")
        cwd_patcher.start()
        self.addCleanup(cwd_patcher.stop)

    def run_log_path(self):
        return Path(self.data_dir.name) / "projects" / "fake-project-for-thresholds-tests" / "run.log"


class TestThresholdsNoOverride(ThresholdsTestCase):
    def test_returns_shipped_defaults_when_no_override_file(self):
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_stays_silent_when_no_override_file(self):
        settings.thresholds()
        self.assertFalse(self.run_log_path().exists())


class TestShippedConfigIsActuallyRead(ThresholdsTestCase):
    """The shipped file has to be the source of the defaults, not a description of them.

    Without these, `smartcompact.yaml` could sit in the repo saying one thing
    while the hooks used another, and every test would still pass.
    """

    def setUp(self):
        super().setUp()
        self.plugin_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.plugin_root.cleanup)
        self.shipped = Path(self.plugin_root.name) / "smartcompact.yaml"
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": self.plugin_root.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shipped_values_are_used_not_the_fallback_constants(self):
        self.shipped.write_text("soft: 0.25\nhard: 0.75\n")
        self.assertEqual(settings.thresholds(), (0.25, 0.75))

    def test_the_real_shipped_file_matches_the_ruled_numbers(self):
        real = Path(__file__).resolve().parents[3] / "smartcompact.yaml"
        parsed, reason = settings._parse_flat_yaml(real)
        self.assertIsNotNone(parsed, reason)
        soft, hard, reason = settings._validated(parsed)
        self.assertIsNotNone(soft, reason)
        self.assertEqual((soft, hard), (0.60, 0.80))

    def test_an_override_still_beats_the_shipped_file(self):
        self.shipped.write_text("soft: 0.25\nhard: 0.75\n")
        self.override_path.write_text("soft: 0.35\nhard: 0.65\n")
        self.assertEqual(settings.thresholds(), (0.35, 0.65))

    def test_an_unreadable_shipped_file_falls_back_and_records_it(self):
        self.shipped.write_text("soft: not-a-number\nhard: 0.80\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))
        self.assertIn("invalid-shipped", self.run_log_path().read_text())

    def test_a_broken_shipped_file_does_not_stop_a_valid_override(self):
        self.shipped.write_text("nonsense without a separator\n")
        self.override_path.write_text("soft: 0.35\nhard: 0.65\n")
        self.assertEqual(settings.thresholds(), (0.35, 0.65))


class TestThresholdsValidOverride(ThresholdsTestCase):
    def test_returns_override_values(self):
        self.override_path.write_text("soft: 0.5\nhard: 0.75\n")
        self.assertEqual(settings.thresholds(), (0.5, 0.75))

    def test_ignores_blank_lines_and_comments(self):
        self.override_path.write_text("# a user override\n\nsoft: 0.4\n# inline comment above\nhard: 0.9\n")
        self.assertEqual(settings.thresholds(), (0.4, 0.9))

    def test_tolerates_quoted_values(self):
        self.override_path.write_text("soft: \"0.45\"\nhard: '0.85'\n")
        self.assertEqual(settings.thresholds(), (0.45, 0.85))

    def test_valid_override_does_not_write_to_run_log(self):
        self.override_path.write_text("soft: 0.5\nhard: 0.75\n")
        settings.thresholds()
        self.assertFalse(self.run_log_path().exists())


class TestThresholdsInvalidOverride(ThresholdsTestCase):
    def test_soft_greater_than_or_equal_to_hard_falls_back_to_defaults(self):
        self.override_path.write_text("soft: 0.8\nhard: 0.6\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_out_of_range_value_falls_back_to_defaults(self):
        self.override_path.write_text("soft: 0.5\nhard: 1.5\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_non_numeric_value_falls_back_to_defaults(self):
        self.override_path.write_text("soft: banana\nhard: 0.8\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_nested_content_falls_back_to_defaults(self):
        # Both keys present and individually valid, but the indented third
        # line is nesting this flat parser refuses to guess the meaning of.
        self.override_path.write_text("soft: 0.5\nhard: 0.8\n  extra: nested\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_missing_key_falls_back_to_defaults(self):
        self.override_path.write_text("soft: 0.5\n")
        self.assertEqual(settings.thresholds(), (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))

    def test_each_invalid_case_records_why_via_runlog(self):
        for content in ("soft: 0.8\nhard: 0.6\n", "soft: 0.5\nhard: 1.5\n", "soft: banana\nhard: 0.8\n"):
            with self.subTest(content=content):
                run_log = self.run_log_path()
                if run_log.exists():
                    run_log.unlink()
                self.override_path.write_text(content)
                settings.thresholds()
                self.assertTrue(run_log.exists())
                self.assertIn("invalid-override", run_log.read_text())

    def test_directory_instead_of_file_does_not_raise(self):
        self.override_path.mkdir()
        result = settings.thresholds()
        self.assertEqual(result, (settings.FALLBACK_SOFT, settings.FALLBACK_HARD))


if __name__ == "__main__":
    unittest.main()


class TestTriggerSelfCalibrates(ThresholdsTestCase):
    """A recorded automatic boundary beats a configured window.

    The configured value can be wrong in a way nothing else detects: a session
    started with a --autocompact flag overrides the settings file without
    writing it down. A recorded automatic boundary is the client stating where
    it actually compacts, so it wins.
    """

    def setUp(self):
        super().setUp()
        self.project = Path(self.data_dir.name) / "projects" / "fake-project-for-thresholds-tests"
        self.project.mkdir(parents=True, exist_ok=True)
        self.boundaries = self.project / "boundaries.jsonl"

    def write(self, records):
        self.boundaries.write_text("".join(json.dumps(r) + "\n" for r in records))

    def test_no_boundaries_falls_back_to_the_configured_window(self):
        with mock.patch.object(settings, "auto_compact_window", return_value=500_000):
            self.assertEqual(settings.trigger(self.project), 500_000 - occupancy.RESERVE)

    def test_one_automatic_boundary_wins_over_the_configured_window(self):
        self.write([{"trigger": "auto", "occupancy": 66_400}])
        with mock.patch.object(settings, "auto_compact_window", return_value=500_000):
            self.assertEqual(settings.trigger(self.project), 66_400)

    def test_the_earliest_fire_is_the_estimate_not_the_latest(self):
        # Every fire is at or above the trigger, because the check runs between
        # turns and one turn can overshoot. The smallest is closest to the truth.
        self.write(
            [
                {"trigger": "auto", "occupancy": 69_889},
                {"trigger": "auto", "occupancy": 64_980},
                {"trigger": "auto", "occupancy": 65_381},
            ]
        )
        self.assertEqual(settings.trigger(self.project), 64_980)

    def test_manual_boundaries_are_ignored(self):
        # A person compacting when they feel like it says nothing about where
        # the client would have forced one.
        self.write([{"trigger": "manual", "occupancy": 12_000}])
        with mock.patch.object(settings, "auto_compact_window", return_value=500_000):
            self.assertEqual(settings.trigger(self.project), 500_000 - occupancy.RESERVE)

    def test_a_torn_or_junk_line_does_not_stop_the_rest(self):
        self.boundaries.write_text(
            json.dumps({"trigger": "auto", "occupancy": 70_000})
            + "\nnot json at all\n"
            + '{"trigger": "auto", "occupancy": 6'
            + "\n"
            + json.dumps({"trigger": "auto", "occupancy": 66_000})
            + "\n"
        )
        self.assertEqual(settings.trigger(self.project), 66_000)

    def test_unanchored_when_nothing_is_measured_and_nothing_configured(self):
        with mock.patch.object(settings, "auto_compact_window", return_value=None):
            self.assertIsNone(settings.trigger(self.project))

    def test_no_project_dir_still_answers_from_config(self):
        with mock.patch.object(settings, "auto_compact_window", return_value=500_000):
            self.assertEqual(settings.trigger(None), 500_000 - occupancy.RESERVE)
