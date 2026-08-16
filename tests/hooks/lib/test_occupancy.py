"""occupancy.py: the pure arithmetic. No filesystem, no environment."""

import unittest

from lib import occupancy


class TestOccupancy(unittest.TestCase):
    def test_none_usage_is_zero(self):
        self.assertEqual(occupancy.occupancy(None), 0)

    def test_empty_dict_is_zero(self):
        self.assertEqual(occupancy.occupancy({}), 0)

    def test_sums_the_three_fields(self):
        usage = {"input_tokens": 100, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 5}
        self.assertEqual(occupancy.occupancy(usage), 125)

    def test_missing_fields_default_to_zero(self):
        self.assertEqual(occupancy.occupancy({"input_tokens": 40}), 40)

    def test_ignores_unrelated_fields(self):
        usage = {"input_tokens": 10, "output_tokens": 99999, "cache_read_input_tokens": 0}
        self.assertEqual(occupancy.occupancy(usage), 10)

    def test_non_dict_usage_does_not_raise_and_is_zero(self):
        for bad in ("a string", 12345, ["a", "list"], object()):
            with self.subTest(bad=bad):
                self.assertEqual(occupancy.occupancy(bad), 0)


class TestTriggerPoint(unittest.TestCase):
    def test_subtracts_reserve_from_window(self):
        self.assertEqual(occupancy.trigger_point(250_000), 250_000 - occupancy.RESERVE)

    def test_none_window_is_none(self):
        self.assertIsNone(occupancy.trigger_point(None))

    def test_zero_window_is_none(self):
        self.assertIsNone(occupancy.trigger_point(0))

    def test_negative_window_is_none(self):
        self.assertIsNone(occupancy.trigger_point(-500))

    def test_non_numeric_window_does_not_raise_and_is_none(self):
        for bad in ("500000", [500_000], {"window": 500_000}):
            with self.subTest(bad=bad):
                self.assertIsNone(occupancy.trigger_point(bad))


class TestZone(unittest.TestCase):
    def test_none_trigger_is_none(self):
        self.assertIsNone(occupancy.zone(1000, None, 0.60, 0.80))

    def test_below_soft_edge_is_green(self):
        # trigger=1000, soft edge=600: comfortably under it.
        self.assertEqual(occupancy.zone(100, 1000, 0.60, 0.80), "green")

    def test_at_soft_edge_is_orange(self):
        # soft edge is inclusive of the boundary itself (>= counts as past it).
        self.assertEqual(occupancy.zone(600, 1000, 0.60, 0.80), "orange")

    def test_between_soft_and_hard_is_orange(self):
        self.assertEqual(occupancy.zone(700, 1000, 0.60, 0.80), "orange")

    def test_at_hard_edge_is_red(self):
        self.assertEqual(occupancy.zone(800, 1000, 0.60, 0.80), "red")

    def test_above_hard_edge_is_red(self):
        self.assertEqual(occupancy.zone(950, 1000, 0.60, 0.80), "red")

    def test_malformed_value_does_not_raise_and_is_none(self):
        self.assertIsNone(occupancy.zone("not a number", 1000, 0.60, 0.80))

    def test_malformed_soft_does_not_raise_and_is_none(self):
        self.assertIsNone(occupancy.zone(500, 1000, "not a number", 0.80))

    def test_malformed_hard_does_not_raise_and_is_none(self):
        self.assertIsNone(occupancy.zone(500, 1000, 0.60, None))


if __name__ == "__main__":
    unittest.main()
