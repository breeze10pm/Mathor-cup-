"""Cases pin time separation, same-label formulas, ties and missing-window policy."""

import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from complete_question1 import (
    clean_field,
    contrast,
    last_label,
    reference_anchors,
    window_summary,
    pair_difference,
    net_radiation,
    select_families,
)


class QuestionOneBoundaries(unittest.TestCase):
    def test_real_radiation_qc_case_and_independent_qc4_view(self):
        frame = pd.DataFrame({"Rld(W/m2)": [0.0, 2.0, 9999.9, np.nan], "QC_rld": [0, 4, 0, 0]})
        a = clean_field(frame, "Rld(W/m2)", [0])
        b = clean_field(frame, "Rld(W/m2)", [0, 4])
        self.assertEqual(a.iloc[0], 0.0)
        self.assertTrue(np.isnan(a.iloc[1]))
        self.assertEqual(b.iloc[1], 2.0)
        self.assertTrue(np.isnan(b.iloc[2]))
        self.assertEqual(frame.iloc[2, 0], 9999.9)
        with self.assertRaises(ValueError):
            clean_field(frame.drop(columns="QC_rld"), "Rld(W/m2)", [0])

    def test_guard_excludes_onset_hour_without_fabricating_exact_trigger(self):
        self.assertEqual(
            last_label("2026-08-26T10:52:00+08:00", 1), pd.Timestamp("2026-08-26 09:00")
        )

    def test_reference_same_clock_calendar_and_no_event_year(self):
        a = reference_anchors(pd.Timestamp("2026-08-26 09:00"), [2022, 2023, 2024, 2025], 15)
        self.assertEqual(len(a), 124)
        self.assertTrue(all(x.hour == 9 and x.year < 2026 for x in a))
        self.assertEqual(a[0], pd.Timestamp("2022-08-11 09:00"))

    def test_window_counts_labels_and_does_not_fill_missing(self):
        s = pd.Series(
            [0.0, np.nan, 2.0, 4.0], index=pd.date_range("2026-01-01", periods=4, freq="h")
        )
        m, n = window_summary(s, s.index[-1], 4, 0.75)
        self.assertEqual((m, n), (2.0, 3))
        m, n = window_summary(s, s.index[-1], 4, 1.0)
        self.assertTrue(np.isnan(m))
        self.assertEqual(n, 3)
        self.assertTrue(np.isnan(s.iloc[1]))

    def test_midrank_ties_and_constant_reference_do_not_create_extreme(self):
        d = contrast(2.0, np.array([1.0, 2.0, 2.0, 3.0]), 4)
        self.assertEqual(d["percentile"], 50.0)
        self.assertEqual(d["D"], 0.0)
        self.assertTrue(np.isnan(contrast(2.0, np.ones(4) * 2, 4)["robust_z"]))
        self.assertTrue(np.isnan(contrast(2.0, np.ones(3), 4)["D"]))

    def test_difference_and_radiation_require_simultaneous_components(self):
        a = pd.Series([2.0, np.nan])
        b = pd.Series([1.0, 3.0])
        d = pair_difference(a, b, 18)
        self.assertAlmostEqual(d.iloc[0], 1 / 18)
        self.assertTrue(np.isnan(d.iloc[1]))
        n = net_radiation(a, b, b, a)
        self.assertEqual(n.iloc[0], 0.0)
        self.assertTrue(np.isnan(n.iloc[1]))

    def test_top_five_are_distinct_families_and_no_nan_backfill(self):
        t = pd.DataFrame(
            {
                "feature": list("abcdefg"),
                "family": ["A", "A", "B", "C", "D", "E", "F"],
                "D": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, np.nan],
                "order": range(7),
            }
        )
        r = select_families(t)
        self.assertEqual(r.feature.tolist(), list("acdef"))
        self.assertEqual(r.family.nunique(), 5)


if __name__ == "__main__":
    unittest.main()
