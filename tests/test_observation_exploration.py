"""重要统计边界；不依赖竞赛原始文件。"""

import sys
from pathlib import Path
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    from explore_observations import missing_runs, record_states, qc_labels, in_declared_window
except ImportError:
    missing_runs = record_states = qc_labels = in_declared_window = None


class ObservationBoundaries(unittest.TestCase):
    def test_catalog_epoch_milliseconds_match_detail_beijing_labels(self):
        import explore_observations

        decode = getattr(explore_observations, "declared_window", None)
        self.assertIsNotNone(decode, "Catalog epoch and display labels need explicit decoding")
        detail = {"startTime": "2021-04-26 20:00:00", "endTime": "2026-08-27 08:00:00"}
        export = {"startTime": 1619438400000, "endTime": 1787788800000}
        self.assertEqual(
            decode(detail, export),
            (pd.Timestamp(detail["startTime"]), pd.Timestamp(detail["endTime"])),
        )

    def test_cross_year_run_counts_both_endpoint_labels(self):
        self.assertIsNotNone(missing_runs, "missing-run implementation is required")
        s = pd.Series(
            [1.0, None, None, 2.0], index=pd.date_range("2025-12-31 22:00", periods=4, freq="h")
        )
        result = missing_runs(s)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["hours"], 2)
        self.assertEqual(result[0]["start_label"], "2025-12-31 23:00:00")
        self.assertEqual(result[0]["end_label"], "2026-01-01 00:00:00")
        self.assertEqual(result[0]["position"], "internal")

    def test_all_missing_and_edge_runs_are_not_lost(self):
        self.assertIsNotNone(missing_runs)
        idx = pd.date_range("2026-01-01", periods=4, freq="h")
        self.assertEqual(
            missing_runs(pd.Series([None] * 4, index=idx))[0]["position"], "entire_window"
        )
        result = missing_runs(pd.Series([None, 1, 2, None], index=idx))
        self.assertEqual([r["position"] for r in result], ["leading", "trailing"])

    def test_missing_classes_are_mutually_exclusive(self):
        self.assertIsNotNone(record_states)
        raw = pd.Series([None, "NAN", 9999.9, float("inf"), 0, -1])
        self.assertEqual(
            record_states(raw, 9999.9).tolist(),
            [
                "native_missing",
                "nonnumeric",
                "official_missing",
                "nonfinite",
                "finite_record",
                "finite_record",
            ],
        )

    def test_missing_qc_column_remains_unprovided(self):
        self.assertIsNotNone(qc_labels)
        frame = pd.DataFrame(
            {"Precip(mm)": [0, 9999.9], "WS_2m(m/s)": [1, None], "QC_WS_2m": [8, 0]}
        )
        original = frame.copy(deep=True)
        self.assertEqual(qc_labels(frame, "Precip(mm)").tolist(), ["not_provided"] * 2)
        self.assertEqual(qc_labels(frame, "WS_2m(m/s)").tolist(), ["8", "0"])
        pd.testing.assert_frame_equal(frame, original)

    def test_window_includes_endpoints_without_future_padding(self):
        self.assertIsNotNone(in_declared_window)
        index = pd.date_range("2026-08-27 07:00", periods=4, freq="h")
        mask = in_declared_window(
            index, pd.Timestamp("2026-08-27 08:00"), pd.Timestamp("2026-08-27 09:00")
        )
        self.assertEqual(mask.tolist(), [False, True, True, False])


if __name__ == "__main__":
    unittest.main()
