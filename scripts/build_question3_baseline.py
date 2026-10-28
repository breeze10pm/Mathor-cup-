"""Build an evidence-labeled retrospective baseline for competition Question 3."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "question3-scenario.json"
RUNOUT_CONFIG = ROOT / "config" / "question4-kinematic.json"
EVENT_CONTEXT = ROOT / "output" / "event_context" / "event_context_summary.json"
OUT = ROOT / "output" / "question3"


def dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timezone required: {value}")
    return parsed


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    runout_cfg = json.loads(RUNOUT_CONFIG.read_text(encoding="utf-8"))
    if not EVENT_CONTEXT.exists():
        raise FileNotFoundError("Run scripts/prepare_event_context.py before the Question 3 baseline")
    event = json.loads(EVENT_CONTEXT.read_text(encoding="utf-8"))
    onset = dt(cfg["ice_collapse_onset"])
    arrival = dt(cfg["arrival_at_port"])
    trigger_start = dt(cfg["trigger_constraint_start"])
    trigger_end = dt(cfg["trigger_constraint_end"])
    init = dt(cfg["forecast_initialization_utc"])

    elapsed_s = (arrival - onset).total_seconds()
    if elapsed_s <= 0 or trigger_end < trigger_start:
        raise ValueError("Event chronology is not ordered")
    init_to_onset_h = (onset.astimezone(init.tzinfo) - init).total_seconds() / 3600
    init_to_arrival_h = (arrival.astimezone(init.tzinfo) - init).total_seconds() / 3600
    routes = event["route_candidates"]
    distance_values = [float(route["centerline_distance_km"]) for route in routes]
    distance_range = [min(distance_values), max(distance_values)]
    distance_m = float(np.mean(distance_values)) * 1000
    baseline_speed = distance_m / elapsed_s
    warning_scenarios = {}
    for name, factor in runout_cfg["scenario_speed_factors"].items():
        duration_s = distance_m / (baseline_speed * float(factor))
        warning_scenarios[name] = {
            "travel_time_minutes": duration_s / 60,
            "arrival_if_detected_at_onset": pd.Timestamp(onset + pd.Timedelta(seconds=duration_s)).isoformat(),
        }

    # This interval is a transparent uniform scenario within the user's hard
    # temporal constraint, not a data-calibrated confidence interval.
    trigger_span_s = (trigger_end - trigger_start).total_seconds()
    tail_s = trigger_span_s * 0.025
    uniform_95 = [trigger_start + pd.Timedelta(seconds=tail_s), trigger_end - pd.Timedelta(seconds=tail_s)]
    summary = {
        "question": 3,
        "method": "retrospective event-time constraint plus forecast-initialization lag; not a trained probabilistic forecast",
        "ice_collapse_onset": onset.isoformat(),
        "arrival_at_port": arrival.isoformat(),
        "reported_onset_to_arrival_minutes": elapsed_s / 60,
        "conditional_trigger_interval": [trigger_start.isoformat(), trigger_end.isoformat()],
        "interval_basis": cfg["trigger_constraint_assumption"],
        "statistical_95_percent_confidence_interval": "not estimable from available observations: one event and no calibrated event-time error distribution",
        "illustrative_95_percent_scenario_interval": [x.isoformat() for x in uniform_95],
        "illustrative_95_percent_scenario_assumption": "uniform trigger-time distribution over the conditional 10:52–10:59 bound; this is a prior scenario, not a statistical confidence interval",
        "empirical_interval_coverage_rate": "not estimable: no independent labeled event sample",
        "forecast_initialization_utc": init.isoformat(),
        "initialization_to_onset_hours": init_to_onset_h,
        "initialization_to_arrival_hours": init_to_arrival_h,
        "operational_warning_time": "unknown: product publication time and actual warning issue time are unavailable",
        "conditional_perfect_detection_lead_minutes": elapsed_s / 60,
        "conditional_perfect_detection_lead_assumption": "A hypothetical detector identifies ice-collapse onset at the reported onset time; this is not an achieved warning lead.",
        "conditional_warning_model": {
            "rule": "After confirmed upstream ice-collapse detection, estimate downstream arrival from the source-projection-to-port centerline distance divided by an event-anchored apparent chain speed.",
            "speed_scenarios": warning_scenarios,
            "status": "retrospective, event-anchored sensitivity scenario; not an operational forecast or calibrated interval",
        },
        "reported_spatial_runout_km": cfg["reported_runout_distance_km"],
        "centerline_source_projection_to_port_distance_range_km": distance_range,
        "centerline_route_candidates": routes,
        "spatial_distance_status": "measured along the public centerline between nearest projections of alternative reported source points and the official core-area reference point; source points remain about 1.0–1.4 km lateral from the line",
        "spatial_prediction_range": "use the UNESCO/UNOSAT satellite-interpreted extents as comparison bounds; not a calibrated predictive footprint",
        "evidence_status": "event times and distance are user-reported; forecast initialization is known but issue/availability time is not",
    }
    (OUT / "question3_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = [
        ("reported_ice_collapse_onset", onset.isoformat(), "user-reported; minute precision"),
        ("conditional_trigger_earliest", trigger_start.isoformat(), "conditional lower bound; not a point label"),
        ("conditional_trigger_latest", trigger_end.isoformat(), "conditional upper bound; not a point label"),
        ("reported_port_arrival", arrival.isoformat(), "user-reported; minute precision"),
        ("contest_literal_time", cfg.get("contest_literal_time", "2026-08-26T10:30:00"), "contest text; event stage and timezone unresolved; conflict retained"),
        ("forecast_initialization", init.isoformat(), "UTC model initialization; release time unknown"),
    ]
    pd.DataFrame(rows, columns=["metric", "value", "evidence_status"]).to_csv(
        OUT / "question3_timeline.csv", index=False
    )
    pd.DataFrame(
        [
            ("hard_conditional_bound", trigger_start.isoformat(), trigger_end.isoformat(), "same-chain assumption only; not probabilistic"),
            ("illustrative_uniform_90pct", (trigger_start + pd.Timedelta(seconds=trigger_span_s * 0.05)).isoformat(), (trigger_end - pd.Timedelta(seconds=trigger_span_s * 0.05)).isoformat(), "uniform prior scenario; not calibrated"),
            ("illustrative_uniform_95pct", uniform_95[0].isoformat(), uniform_95[1].isoformat(), "uniform prior scenario; not a statistical confidence interval"),
            ("illustrative_uniform_99pct", (trigger_start + pd.Timedelta(seconds=trigger_span_s * 0.005)).isoformat(), (trigger_end - pd.Timedelta(seconds=trigger_span_s * 0.005)).isoformat(), "uniform prior scenario; not calibrated"),
        ],
        columns=["interval_type", "lower", "upper", "assumption"],
    ).to_csv(OUT / "question3_trigger_time_scenarios.csv", index=False)
    pd.DataFrame(
        [
            ("onset_to_arrival_elapsed_min", elapsed_s / 60, "reported chronology; not debris-flow-only travel time"),
            ("initialization_to_onset_h", init_to_onset_h, "hindcast initialization lag; not operational lead"),
            ("initialization_to_arrival_h", init_to_arrival_h, "hindcast initialization lag; not operational lead"),
            ("conditional_perfect_detection_lead_min", elapsed_s / 60, "hypothetical immediate onset detection only"),
            ("reported_runout_distance_km", cfg["reported_runout_distance_km"], "approximate user-reported distance"),
            ("centerline_route_distance_A_km", routes[0]["centerline_distance_km"], "nearest centerline projections; not a measured flow path"),
            ("centerline_route_distance_B_km", routes[1]["centerline_distance_km"], "nearest centerline projections; not a measured flow path"),
        ],
        columns=["metric", "value", "interpretation"],
    ).to_csv(OUT / "question3_metrics.csv", index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
