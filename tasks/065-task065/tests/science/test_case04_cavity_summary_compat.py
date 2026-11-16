import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from mvp_numeric import _check_cavity_summary_fields


class CavitySummaryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.cavity = np.array([2, 3, 3])
        self.weights = np.array([0.2, 0.3, 0.5])
        self.expected = {
            "cavity_water_count_range": {"min": 2, "max": 3, "observed_zero": False},
            "cavity_occupancy_weighted_distribution": {"2": 0.2, "3": 0.8},
            "cavity_occupancy_weighted_mean": 2.8,
        }

    def check(self, analysis):
        errors = []

        def check_numeric(path, reported, expected):
            if not isinstance(reported, (int, float)) or abs(reported - expected) > 1e-8:
                errors.append({"field": path, "reported": reported, "recomputed": expected})

        _check_cavity_summary_fields(analysis, self.cavity, self.weights, errors, check_numeric)
        return errors

    def test_flat_alias(self):
        self.assertEqual(self.check(self.expected.copy()), [])

    def test_nested_fields(self):
        self.assertEqual(self.check({"weighted_states": self.expected.copy()}), [])

    def test_both_locations_consistent(self):
        self.assertEqual(self.check({**self.expected, "weighted_states": self.expected.copy()}), [])

    def test_conflicting_locations_fail(self):
        bad = self.expected.copy()
        bad["cavity_occupancy_weighted_mean"] = 2.7
        errors = self.check({**self.expected, "weighted_states": bad})
        self.assertEqual([e["field"] for e in errors], ["weighted_states.cavity_occupancy_weighted_mean"])

    def test_missing_both_locations_fail(self):
        errors = self.check({"weighted_states": {}})
        self.assertEqual(len(errors), 3)

    def test_tampered_value_fails(self):
        bad = self.expected.copy()
        bad["cavity_occupancy_weighted_distribution"] = {"2": 0.2, "3": 0.7}
        errors = self.check(bad)
        self.assertTrue(any(e["field"] == "top_level.cavity_occupancy_weighted_distribution.3" for e in errors))


if __name__ == "__main__":
    unittest.main()
