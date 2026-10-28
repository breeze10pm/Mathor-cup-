from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from question3_forecast_model import (  # noqa: E402
    arrival_scenarios,
    build_trigger_intervals,
    elapsed_tolerance_range_seconds,
    forecast_timing,
    parse_aware_datetime,
    validate_event_chronology,
)


class Question3ForecastModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.onset = parse_aware_datetime("2026-08-26T10:52:00+08:00")
        self.transition_start = parse_aware_datetime("2026-08-26T10:54:19+08:00")
        self.transition_end = parse_aware_datetime("2026-08-26T10:55:10+08:00")
        self.arrival = parse_aware_datetime("2026-08-26T10:59:00+08:00")

    def test_timezone_conversion_preserves_same_instant(self) -> None:
        bjt = parse_aware_datetime("2026-08-26T10:52:00+08:00")
        utc = bjt.astimezone(timezone.utc)
        self.assertEqual(utc.isoformat(), "2026-08-26T02:52:00+00:00")

    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_aware_datetime("2026-08-26T10:52:00")

    def test_event_order_uses_instants_across_offsets(self) -> None:
        validate_event_chronology(
            self.onset,
            self.transition_start.astimezone(timezone.utc),
            self.transition_end,
            self.arrival,
        )
        with self.assertRaises(ValueError):
            validate_event_chronology(self.onset, self.transition_end, self.transition_start, self.arrival)

    def test_process_phase_is_not_a_trigger_or_statistical_interval(self) -> None:
        rows = build_trigger_intervals(self.onset, self.transition_start, self.transition_end, self.arrival)
        by_name = {row["interval_id"]: row for row in rows}
        phase = by_name["reported_transition_phase"]
        ci = by_name["nominal_95_prediction_interval"]
        self.assertFalse(phase["is_trigger_time_interval"])
        self.assertFalse(phase["is_statistical"])
        self.assertIsNone(ci["lower_time"])
        self.assertEqual(ci["status"], "not_estimable")

    def test_missing_publication_time_keeps_operational_lead_null(self) -> None:
        init = parse_aware_datetime("2026-08-25T00:00:00+00:00")
        timing = forecast_timing(init, self.onset, publication_time=None)
        self.assertAlmostEqual(timing["initialization_to_event_hours"], 26 + 52 / 60)
        self.assertIsNone(timing["operational_lead_hours"])

    def test_timestamp_precision_sensitivity_is_a_bound_not_a_distribution(self) -> None:
        lower, upper = elapsed_tolerance_range_seconds(self.onset, self.arrival, 30)
        self.assertEqual((lower, upper), (360, 480))

    def test_arrival_scenarios_keep_leakage_and_speed_sensitivity_explicit(self) -> None:
        routes = [
            {"route_id": "source_A", "centerline_distance_km": 22.155652},
            {"route_id": "source_B", "centerline_distance_km": 21.992652},
        ]
        rows = arrival_scenarios(routes, self.onset, self.arrival, {"slow": 0.85, "base": 1.0, "fast": 1.15})
        by_key = {(row["route_id"], row["scenario"]): row for row in rows}
        self.assertAlmostEqual(by_key["source_A", "base"]["centerline_distance_km"], 22.155652)
        self.assertGreater(by_key["source_A", "slow"]["travel_time_seconds"], by_key["source_A", "fast"]["travel_time_seconds"])
        self.assertTrue(by_key["source_A", "base"]["uses_reported_arrival_anchor"])
        self.assertFalse(by_key["source_A", "base"]["independent_validation"])
        self.assertTrue(by_key["source_A", "base"]["arrival_matches_anchor_by_construction"])


if __name__ == "__main__":
    unittest.main()
