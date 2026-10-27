"""Non-rain descriptive boundaries on synthetic inputs, without raw attachments."""

import importlib
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    relation = importlib.import_module("analyze_variable_relations")
except ModuleNotFoundError:
    relation = None


class VariableRelationBoundaries(unittest.TestCase):
    def api(self, name):
        self.assertIsNotNone(relation, "Non-rain daily relation implementation is required")
        function = getattr(relation, name, None)
        self.assertIsNotNone(function, f"Missing required operation: {name}")
        return function

    def test_qc4_is_optional_not_silently_direct_observation(self):
        aggregate = self.api("daily_medians")
        index = pd.date_range("2022-01-01", periods=24, freq="h")
        values = pd.DataFrame({"x": list(range(24))}, index=index)
        quality = pd.DataFrame({"x": [0] * 17 + [4] * 7}, index=index)
        before = values.copy(deep=True)
        strict, count0 = aggregate(values, quality, {0})
        broad, count4 = aggregate(values, quality, {0, 4})
        self.assertTrue(pd.isna(strict.iloc[0, 0]))
        self.assertEqual(count0.iloc[0, 0], 17)
        self.assertEqual(count4.iloc[0, 0], 24)
        self.assertEqual(broad.iloc[0, 0], 11.5)
        pd.testing.assert_frame_equal(values, before)

    def test_18_numeric_labels_gate_excludes_missing_sentinel_infinite_and_bad_qc(self):
        aggregate = self.api("daily_medians")
        index = pd.date_range("2022-01-01", periods=48, freq="h")
        day = list(range(18)) + [None, "NAN", 9999.9, np.inf, 777, 888]
        quality_day = [0] * 22 + [2, 9]
        values = pd.DataFrame({"x": day + [0] * 17 + [None] * 7}, index=index)
        quality = pd.DataFrame({"x": quality_day + [0] * 24}, index=index)
        result, counts = aggregate(values, quality, {0})
        self.assertEqual(counts.x.tolist(), [18, 17])
        self.assertEqual(result.x.iloc[0], 8.5)
        self.assertTrue(pd.isna(result.x.iloc[1]))

    def test_daily_calendar_labels_use_beijing_day_without_hour_shift(self):
        aggregate = self.api("daily_medians")
        index = pd.date_range("2022-01-01 23:00", periods=3, freq="h")
        values = pd.DataFrame({"x": [1, 2, 3]}, index=index)
        result, counts = aggregate(values, values * 0, {0})
        self.assertEqual(counts.x.tolist(), [1, 2])
        self.assertEqual(str(result.index[0].date()), "2022-01-01")

    def test_duplicate_labels_cannot_count_twice_toward_daily_threshold(self):
        aggregate = self.api("daily_medians")
        index = pd.DatetimeIndex(["2022-01-01"] * 18)
        values = pd.DataFrame({"x": range(18)}, index=index)
        with self.assertRaises(ValueError):
            aggregate(values, values * 0, {0})

    def test_pairwise_overlap_under_30_remains_missing_not_zero(self):
        correlate = self.api("pairwise_spearman")
        index = pd.date_range("2022-01-01", periods=40)
        daily = pd.DataFrame({"a": range(40), "b": range(40)}, index=index, dtype=float)
        daily.loc[index[:11], "b"] = np.nan
        result = correlate(daily, "qc0", "raw_daily")
        row = result.loc[result.period.eq("2022-2025")].iloc[0]
        self.assertEqual(row.n_matched_days, 29)
        self.assertTrue(pd.isna(row.spearman_rho))
        self.assertEqual(row.status, "fewer_than_30_pairs")

    def test_pairwise_30_is_spearman_with_ties_and_constant_is_missing(self):
        correlate = self.api("pairwise_spearman")
        index = pd.date_range("2022-01-01", periods=30)
        daily = pd.DataFrame({"a": [0] * 15 + [1] * 15, "b": [9] * 15 + [2] * 15, "c": 5.0}, index=index)
        result = correlate(daily, "qc0", "raw_daily")
        rows = result.loc[result.period.eq("2022-2025")].set_index(["field_a", "field_b"])
        self.assertAlmostEqual(rows.loc[("a", "b"), "spearman_rho"], -1)
        self.assertEqual(rows.loc[("a", "c"), "status"], "constant_series")
        self.assertTrue(pd.isna(rows.loc[("a", "c"), "spearman_rho"]))

    def test_partial_reference_years_are_excluded_and_n_is_pair_specific(self):
        correlate = self.api("pairwise_spearman")
        index = pd.date_range("2021-12-01", "2026-02-01")
        daily = pd.DataFrame({"a": np.arange(len(index)), "b": -np.arange(len(index)), "c": np.arange(len(index))}, index=index, dtype=float)
        daily.loc["2022-01-01":"2022-01-10", "c"] = np.nan
        result = correlate(daily, "qc0", "raw_daily")
        rows = result.loc[result.period.eq("2022-2025")].set_index(["field_a", "field_b"])
        self.assertEqual(rows.loc[("a", "b"), "n_matched_days"], 1461)
        self.assertEqual(rows.loc[("a", "c"), "n_matched_days"], 1451)
        self.assertEqual(set(result.period), {"2022-2025", "2022", "2023", "2024", "2025"})

    def test_within_year_month_centering_preserves_missing_and_separates_years(self):
        center = self.api("within_year_month_center")
        index = pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03", "2022-02-01", "2023-01-01"])
        daily = pd.DataFrame({"a": [1, 5, None, 100, 200]}, index=index)
        result = center(daily)
        self.assertEqual(result.a.dropna().tolist(), [-2, 2, 0, 0])
        self.assertTrue(pd.isna(result.a.iloc[2]))

    def test_plots_render_actual_correlation_tables_to_four_nonempty_files(self):
        plot = self.api("make_plots")
        dictionary = pd.DataFrame(relation.SELECTED, columns=["group", "field", "short_name", "physical_group", "interpretation"])
        index = pd.date_range("2022-01-01", periods=60)
        daily = pd.DataFrame({name: np.sin(np.arange(60) / (i + 2)) for i, name in enumerate(dictionary.field)}, index=index)
        raw = relation.pairwise_spearman(daily, "qc0", "raw_daily")
        centered = relation.pairwise_spearman(relation.within_year_month_center(daily), "qc0", "within_year_month_centered")
        with tempfile.TemporaryDirectory() as location, patch.object(relation, "OUT", Path(location)):
            plot(pd.concat([raw, centered], ignore_index=True), dictionary)
            for filename in ["correlation_heatmaps.png", "correlation_heatmaps.svg", "year_variability.png", "year_variability.svg"]:
                self.assertGreater((Path(location) / filename).stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
