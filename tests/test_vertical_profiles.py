"""Synthetic checks of simultaneous profile eligibility and descriptive bins."""

import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    profile = importlib.import_module("analyze_vertical_profiles")
except ModuleNotFoundError:
    profile = None


class VerticalProfileBoundaries(unittest.TestCase):
    def api(self, name):
        self.assertIsNotNone(profile, "Vertical-profile implementation is required")
        return getattr(profile, name)

    def inputs(self, periods=3):
        index = pd.date_range("2022-01-01", periods=periods, freq="h")
        values = pd.DataFrame(
            {h: np.full(periods, h, dtype=float) for h in [1, 2, 4, 10, 20]}, index=index
        )
        return values, values * 0

    def test_full_profile_has_one_shared_same_time_mask_not_heightwise_medians(self):
        fn = self.api("eligible_profiles")
        values, qc = self.inputs()
        values[1] = [0, 100, 50]
        values[20] = [10, 120, 70]
        values.loc[values.index[1], 4] = np.nan
        selected, mask = fn(values, qc, {0})
        self.assertEqual(mask.tolist(), [True, False, True])
        self.assertTrue(selected.iloc[1].isna().all())
        self.assertEqual(selected[1].median(), 25)
        self.assertEqual(selected[20].median(), 40)

    def test_difference_is_same_time_not_difference_of_separate_medians(self):
        fn = self.api("paired_gradients")
        values, qc = self.inputs()
        values[2], values[20] = [0, 100, 101], [10, 101, 200]
        result = fn(values, qc, {0})[(2, 20)]
        self.assertEqual(result.difference.tolist(), [10, 1, 99])
        self.assertEqual(result.difference.median(), 10)
        self.assertNotEqual(result.difference.median(), values[20].median() - values[2].median())
        self.assertEqual(result.gradient.median(), 10 / 18)

    def test_actual_layer_spacing_and_pair_specific_eligibility(self):
        fn = self.api("paired_gradients")
        values, qc = self.inputs()
        values.iloc[0, 2] = np.nan
        result = fn(values, qc, {0})
        for (lower, upper), paired in result.items():
            self.assertEqual(paired.gradient.dropna().unique().tolist(), [1.0])
            self.assertEqual(paired.eligible.sum(), 2 if 4 in [lower, upper] else 3)
            self.assertTrue((paired.difference.dropna() == upper - lower).all())

    def test_qc4_views_are_independent_and_no_imputation_or_input_mutation(self):
        fn = self.api("eligible_profiles")
        values, qc = self.inputs()
        qc.loc[values.index[0], 1] = 4
        values.loc[values.index[1], 20] = 9999.9
        values.loc[values.index[2], 10] = np.inf
        before_values, before_qc = values.copy(deep=True), qc.copy(deep=True)
        strict, mask0 = fn(values, qc, {0})
        broad, mask4 = fn(values, qc, {0, 4})
        self.assertFalse(mask0.any())
        self.assertEqual(mask4.tolist(), [True, False, False])
        self.assertTrue(strict.isna().all().all())
        self.assertEqual(broad.iloc[0, 0], 1)
        pd.testing.assert_frame_equal(values, before_values)
        pd.testing.assert_frame_equal(qc, before_qc)

    def test_axes_missing_height_duplicate_or_timezone_labels_fail_explicitly(self):
        fn = self.api("eligible_profiles")
        values, qc = self.inputs()
        bad_inputs = [
            (values.drop(columns=4), qc.drop(columns=4)),
            (values, qc.rename(columns={1: 99})),
            (values, qc.iloc[::-1]),
            (values.set_axis([values.index[0]] * 3), qc.set_axis([values.index[0]] * 3)),
            (values.tz_localize("UTC"), qc.tz_localize("UTC")),
        ]
        for x, q in bad_inputs:
            with self.subTest(columns=list(x.columns)):
                with self.assertRaises(ValueError):
                    fn(x, q, {0})

    def test_numeric_missing_nonnumeric_bad_qc_excluded_zeros_preserved(self):
        fn = self.api("paired_gradients")
        values, qc = self.inputs(6)
        values[2] = [0, "NAN", 9999.9, -np.inf, 2, 2]
        qc[20] = [0, 0, 0, 0, 2, np.nan]
        paired = fn(values, qc, {0})[(2, 20)]
        self.assertEqual(paired.eligible.tolist(), [True, False, False, False, False, False])
        self.assertEqual(paired.difference.iloc[0], 20)

    def test_bin_counts_are_shared_labels_and_gate_does_not_hide_counts(self):
        fn = self.api("summarize")
        index = pd.date_range("2022-01-01", periods=31, freq="D")
        frame = pd.DataFrame(
            {
                "difference": [1.0] * 15 + [-1.0] * 15 + [np.nan],
                "gradient": [0.5] * 15 + [-0.5] * 15 + [np.nan],
            },
            index=index,
        )
        result = fn(frame, "hour")
        zero, empty = result.loc[result.hour.eq(0)].iloc[0], result.loc[result.hour.eq(1)].iloc[0]
        self.assertEqual(zero.n_eligible, 30)
        self.assertEqual(zero.n_source_labels, 31)
        self.assertEqual(zero.positive_difference_fraction, 0.5)
        self.assertEqual(zero.gradient_q25, -0.5)
        self.assertEqual(zero.gradient_q75, 0.5)
        self.assertEqual(empty.n_eligible, 0)
        self.assertTrue(pd.isna(empty.gradient_median))
        short = fn(frame.iloc[:29], "overall").iloc[0]
        self.assertEqual(short.n_eligible, 29)
        self.assertTrue(pd.isna(short.positive_difference_fraction))
        self.assertEqual(short.status, "fewer_than_30_labels")

    def test_month_hour_bins_preserve_clock_and_complete_empty_grid(self):
        fn = self.api("summarize")
        index = pd.to_datetime(["2022-01-31 23:00", "2022-02-01 00:00"])
        frame = pd.DataFrame({"difference": [1.0, 2.0], "gradient": [1.0, 2.0]}, index=index)
        result = fn(frame, "month_hour")
        self.assertEqual(len(result), 12 * 24)
        self.assertEqual(result.n_source_labels.sum(), 2)
        self.assertEqual(
            result.loc[result.month.eq(1) & result.hour.eq(23), "n_eligible"].iloc[0], 1
        )
        self.assertEqual(
            result.loc[result.month.eq(2) & result.hour.eq(0), "n_eligible"].iloc[0], 1
        )

    def test_joint_temperature_speed_support_requires_both_pairs_same_label(self):
        fn = self.api("simultaneous_temperature_wind")
        values, qc = self.inputs()
        ta = self.api("paired_gradients")(values, qc, {0})
        wind = self.api("paired_gradients")(values, qc, {0})
        ta[(2, 20)].loc[values.index[0], ["difference", "gradient"]] = np.nan
        ta[(2, 20)].loc[values.index[0], "eligible"] = False
        wind[(2, 20)].loc[values.index[1], ["difference", "gradient"]] = np.nan
        wind[(2, 20)].loc[values.index[1], "eligible"] = False
        joint = fn(ta, wind)[(2, 20)]
        self.assertEqual(joint.eligible.tolist(), [False, False, True])
        self.assertTrue(joint.iloc[:2][["ta_gradient", "ws_gradient"]].isna().all().all())


if __name__ == "__main__":
    unittest.main()
