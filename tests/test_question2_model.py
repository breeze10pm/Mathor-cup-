"""Unit tests for the evidence-aware conditional trigger model."""

import math
import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    from question2_model import (
        cascade_state,
        distance_connectivity,
        infinite_slope_factor_of_safety,
        scenario_index,
        slope_membership,
    )
except ImportError:
    cascade_state = distance_connectivity = None
    infinite_slope_factor_of_safety = scenario_index = slope_membership = None


class ConditionalTriggerModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(slope_membership, "the conditional model module is not implemented yet")

    def test_slope_membership_is_bounded_and_preserves_missing_values(self):
        self.assertAlmostEqual(slope_membership(30.0, 20.0, 40.0), 0.5)
        self.assertEqual(slope_membership(10.0, 20.0, 40.0), 0.0)
        self.assertEqual(slope_membership(50.0, 20.0, 40.0), 1.0)
        self.assertTrue(math.isnan(slope_membership(float("nan"), 20.0, 40.0)))

    def test_channel_connectivity_decays_with_distance_and_has_explicit_scale(self):
        self.assertEqual(distance_connectivity(0.0, 500.0), 1.0)
        self.assertGreater(distance_connectivity(100.0, 500.0), distance_connectivity(1000.0, 500.0))
        self.assertTrue(math.isnan(distance_connectivity(float("nan"), 500.0)))

    def test_unknown_required_component_does_not_become_zero_or_one(self):
        self.assertIsNone(scenario_index({"terrain": 0.8, "water": None}))
        self.assertAlmostEqual(scenario_index({"terrain": 0.8, "channel": 0.4}), 0.6)

    def test_missing_water_keeps_transition_indeterminate(self):
        self.assertEqual(cascade_state(source=True, channel=True, water=None), "indeterminate_water_unobserved")
        self.assertEqual(cascade_state(source=True, channel=True, water=True), "conditional_gates_met")
        self.assertEqual(cascade_state(source=False, channel=True, water=True), "source_gate_not_met")

    def test_infinite_slope_limit_equilibrium_has_factor_of_safety_one(self):
        # For zero cohesion and no groundwater, alpha == phi gives FS == 1.
        fs = infinite_slope_factor_of_safety(
            slope_deg=30.0,
            cohesion_kpa=0.0,
            friction_angle_deg=30.0,
            unit_weight_kn_m3=20.0,
            soil_depth_m=1.0,
            saturation_ratio=0.0,
        )
        self.assertAlmostEqual(fs, 1.0)

    def test_invalid_slope_mechanics_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            infinite_slope_factor_of_safety(35, -1, 30, 20, 1, 0.2)


if __name__ == "__main__":
    unittest.main()
