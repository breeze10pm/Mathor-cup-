"""Build the Question 3 evidence, conditional forecast, and spatial package.

All model arrivals are conditional scenarios. The event-anchored speed uses the
reported arrival, so its match is by construction rather than independent skill.
"""

from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyogrio import write_dataframe
from shapely.geometry import LineString, Point

from question3_forecast_model import (
    arrival_scenarios,
    build_trigger_intervals,
    elapsed_tolerance_range_seconds,
    forecast_timing,
    parse_aware_datetime,
    validate_event_chronology,
)


ROOT = Path(__file__).resolve().parents[1]
Q3_CONFIG = ROOT / "config" / "question3-scenario.json"
Q4_CONFIG = ROOT / "config" / "question4-kinematic.json"
EVENT_SUMMARY = ROOT / "output" / "event_context" / "event_context_summary.json"
EVENT_GPKG = ROOT / "output" / "event_context" / "event_context.gpkg"
Q2_FINAL = ROOT / "output" / "question2" / "final"
Q4_OUT = ROOT / "output" / "question4"
OUT = ROOT / "output" / "question3" / "final"
CRS = "EPSG:32645"

OUTPUTS = [
    "event_time_evidence.csv", "forecast_assumptions.csv", "trigger_time_intervals.csv",
    "warning_lead_times.csv", "interval_validation.csv", "spatial_distance_range.csv",
    "q3_arrival_scenarios.csv", "q3_front_trajectories.csv", "question3_sensitivity.csv", "question3_spatial_scenarios.gpkg",
    "question3_timeline.png", "question3_spatial_map.png", "question3_summary.json", "README.md",
]


def _require_inputs() -> None:
    paths = [
        Q3_CONFIG, Q4_CONFIG, EVENT_SUMMARY, EVENT_GPKG,
        Q2_FINAL / "dynamic_weather_context.csv", Q2_FINAL / "temporal_reliability.csv",
        Q4_OUT / "question4_front_trajectories.csv", Q4_OUT / "question4_arrival_sensitivity.csv",
        Q4_OUT / "question4_transition_positions.csv",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing Question 3 inputs: " + ", ".join(missing)
            + ". First run the existing Q2/Q4 preparation and scenario scripts."
        )


def _write_layer(path: Path, frame: gpd.GeoDataFrame, layer: str, *, first: bool = False) -> None:
    write_dataframe(frame, path, layer=layer, driver="GPKG", append=not first)


def _event_evidence(config: dict, initialization) -> pd.DataFrame:
    onset = parse_aware_datetime(config["ice_collapse_onset"])
    transition_start = parse_aware_datetime(config["debris_to_mudflow_transition_start"])
    transition_end = parse_aware_datetime(config["debris_to_mudflow_transition_end"])
    transition_rep = parse_aware_datetime(config["transition_representative_time"])
    arrival = parse_aware_datetime(config["arrival_at_port"])
    contest = config.get("contest_literal_time", "2026-08-26 10:30")
    rows = [
        {"time": contest, "target_stage": "problem_literal_time_stage_unresolved", "timezone": "unknown", "source": "competition problem statement", "reported_precision": "minute label; time-zone and event stage not stated", "evidence_grade": "official text, interpretation unresolved", "is_exact_physical_trigger": False, "notes": config.get("contest_literal_time_interpretation", "retained without reinterpretation")},
        {"time": onset.isoformat(), "target_stage": "ice_rock_avalanche_onset", "timezone": "Asia/Shanghai (UTC+08:00)", "source": "user-provided event timeline; source record not yet supplied", "reported_precision": "minute; measurement/rounding error unknown", "evidence_grade": "user-reported, not independently verified", "is_exact_physical_trigger": False, "notes": "Start of reported ice-rock avalanche; not debris-flow formation time."},
        {"time": transition_start.isoformat(), "target_stage": "debris_to_mudflow_transition_phase_start", "timezone": "Asia/Shanghai (UTC+08:00)", "source": "user-provided timing", "reported_precision": "second in reported timestamp; actual error unknown", "evidence_grade": "user-reported, original record not supplied", "is_exact_physical_trigger": False, "notes": "Start of transition phase; not automatically the physical trigger."},
        {"time": transition_rep.isoformat(), "target_stage": "representative_transition_scenario_anchor", "timezone": "Asia/Shanghai (UTC+08:00)", "source": "user-selected representative time", "reported_precision": "scenario anchor to second; not independent evidence", "evidence_grade": "scenario choice", "is_exact_physical_trigger": False, "notes": "Used only as a deterministic scenario reference."},
        {"time": transition_end.isoformat(), "target_stage": "debris_to_mudflow_transition_phase_end", "timezone": "Asia/Shanghai (UTC+08:00)", "source": "user-provided timing", "reported_precision": "second in reported timestamp; actual error unknown", "evidence_grade": "user-reported, original record not supplied", "is_exact_physical_trigger": False, "notes": "End of transition phase; not a calibrated trigger interval."},
        {"time": None, "target_stage": "physical_debris_flow_trigger", "timezone": "Asia/Shanghai (event timeline convention)", "source": "no direct observation supplied", "reported_precision": "unknown", "evidence_grade": "unobserved", "is_exact_physical_trigger": True, "notes": "Exact physical trigger time remains unknown; no timestamp is imputed."},
        {"time": arrival.isoformat(), "target_stage": "reported_port_arrival", "timezone": "Asia/Shanghai (UTC+08:00)", "source": "user-provided event timeline; source record not yet supplied", "reported_precision": "minute; measurement/rounding error unknown", "evidence_grade": "user-reported, not independently verified", "is_exact_physical_trigger": False, "notes": "Reported arrival at the port core; exact boundary-crossing instant not surveyed."},
        {"time": initialization.isoformat(), "target_stage": "numerical_model_initialization", "timezone": "UTC", "source": "GFS NetCDF global initialization_time and WRF d01 START_DATE/SIMULATION_START_DATE attributes", "reported_precision": "hour", "evidence_grade": "input-file model metadata; not product publication time", "is_exact_physical_trigger": False, "notes": "Initialization precedes the reported event; generation/public availability remain unknown."},
    ]
    return pd.DataFrame(rows)


def _forecast_assumptions(weather: pd.DataFrame, time_scales: pd.DataFrame, initialization, events: dict) -> pd.DataFrame:
    rows: list[dict] = []
    event_times = {
        "reported_ice_onset": parse_aware_datetime(events["ice_collapse_onset"]),
        "reported_transition_start": parse_aware_datetime(events["debris_to_mudflow_transition_start"]),
        "reported_transition_end": parse_aware_datetime(events["debris_to_mudflow_transition_end"]),
        "reported_port_arrival": parse_aware_datetime(events["arrival_at_port"]),
    }
    for model in ("GFS 0.25-degree forecast", "WRF d01 model"):
        model_rows = weather.loc[weather.source_type.eq(model)]
        step_s = 21600 if model.startswith("GFS") else 3600
        space_km = 26.0 if model.startswith("GFS") else 9.01426953125
        scale_name = "GFS 0.25-degree forecast" if model.startswith("GFS") else "WRF d01"
        scale_rows = time_scales.loc[time_scales.dataset.eq(scale_name)]
        scale_ratio = float(scale_rows.iloc[0].time_step_to_window_ratio) if not scale_rows.empty else math.nan
        system_status = "forecast product; issue/publication time not present in local metadata" if model.startswith("GFS") else "regional model output; cannot establish operational forecast/publication status from local metadata"
        rows.append({
            "model": model, "record_type": "cycle_metadata", "site_id": None,
            "initialization_time_utc": initialization.isoformat(), "valid_time_utc": None,
            "generation_time_utc": None, "public_availability_time_utc": None,
            "forecast_hour": None, "time_step_seconds": step_s, "nominal_grid_spacing_km": space_km,
            "time_step_to_51s_phase_ratio": scale_ratio,
            "rain_increment_mm": None, "rain_6h_mm": None, "temperature_2m_c": None,
            "distance_to_nearest_grid_km": None, "status": system_status,
            "uses_temporal_interpolation": False,
        })
        for row in model_rows.to_dict(orient="records"):
            valid = parse_aware_datetime(row["time_utc"])
            lead_deltas = {name: (target - initialization).total_seconds() / 3600 for name, target in event_times.items()}
            rows.append({
                "model": model, "record_type": "valid_time_sample", "site_id": row["site_id"],
                "initialization_time_utc": initialization.isoformat(), "valid_time_utc": valid.isoformat(),
                "generation_time_utc": None, "public_availability_time_utc": None,
                "forecast_hour": row.get("forecast_hour_from_init"), "time_step_seconds": step_s,
                "nominal_grid_spacing_km": float(row["nominal_grid_spacing_km"]),
                "rain_increment_mm": row.get("rain_hour_increment_mm"), "rain_6h_mm": row.get("rain_6h_mm"),
                "temperature_2m_c": row.get("temperature_2m_c"),
                "distance_to_nearest_grid_km": row.get("distance_to_nearest_grid_km"),
                "valid_time_beijing": row.get("time_beijing"),
                "initialization_to_onset_hours": round(lead_deltas["reported_ice_onset"], 6),
                "initialization_to_transition_start_hours": round(lead_deltas["reported_transition_start"], 6),
                "initialization_to_transition_end_hours": round(lead_deltas["reported_transition_end"], 6),
                "initialization_to_arrival_hours": round(lead_deltas["reported_port_arrival"], 6),
                "time_step_to_51s_phase_ratio": scale_ratio,
                "status": system_status,
                "uses_temporal_interpolation": False,
                "notes": row.get("rain_window_unit"),
            })
    return pd.DataFrame(rows)


def _timestamp_sensitivity(onset, transition_start, transition_end, arrival) -> pd.DataFrame:
    rows = []
    chain_exact = (arrival - onset).total_seconds()
    for scenario, tolerance, basis in (
        ("minute_labels_treated_as_exact", 0.0, "Reported values used as reference points; not uncertainty bounds."),
        ("minute_labels_nearest_minute_assumption", 30.0, "Analyst sensitivity: each minute-reported endpoint may deviate by +/-30s; no distribution assumed."),
        ("minute_labels_within_one_minute_bin", 60.0, "Conservative analyst sensitivity: each minute endpoint has +/-60s tolerance; no distribution assumed."),
    ):
        low, high = elapsed_tolerance_range_seconds(onset, arrival, tolerance)
        rows.append({"experiment": "timestamp_precision", "target": "ice_onset_to_port_arrival_elapsed", "scenario": scenario, "endpoint_tolerance_seconds": tolerance, "reference_elapsed_seconds": chain_exact, "lower_elapsed_seconds": low, "upper_elapsed_seconds": high, "is_probability_interval": False, "assumption": basis})
    transition_s = (transition_end - transition_start).total_seconds()
    for scenario, tolerance, basis in (
        ("transition_second_labels_as_exact", 0.0, "Reported second-level endpoints used as reference; actual timing error unknown."),
        ("transition_nearest_second_assumption", 0.5, "Analyst sensitivity: each endpoint rounded to nearest second; not a statistical interval."),
        ("transition_one_second_tolerance", 1.0, "Analyst sensitivity: +/-1s per endpoint; no probability distribution assumed."),
    ):
        low, high = elapsed_tolerance_range_seconds(transition_start, transition_end, tolerance)
        rows.append({"experiment": "timestamp_precision", "target": "reported_transition_phase_duration", "scenario": scenario, "endpoint_tolerance_seconds": tolerance, "reference_elapsed_seconds": transition_s, "lower_elapsed_seconds": low, "upper_elapsed_seconds": high, "is_probability_interval": False, "assumption": basis})
    return pd.DataFrame(rows)


def _plot_timeline(OUT_path: Path, onset, transition_start, transition_end, arrival, contest: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.8), constrained_layout=True)
    x0 = onset.replace(minute=30, second=0)
    x1 = arrival + timedelta(minutes=2)
    ax.hlines(0, x0, x1, color="#475569", lw=2)
    ax.axvspan(onset, arrival, color="#dbeafe", alpha=0.55, label="conditional event-chain bound; not a CI")
    ax.axvspan(transition_start, transition_end, color="#f97316", alpha=0.45, label="reported transition phase (51 s)")
    stages = [
        (onset, 0.15, "Ice-rock onset\n10:52 (reported)", "#2563eb"),
        (transition_start, -0.16, "Transition begins\n10:54:19", "#ea580c"),
        (transition_end, 0.16, "Transition ends\n10:55:10", "#ea580c"),
        (arrival, -0.16, "Port arrival\n10:59 (reported)", "#16a34a"),
    ]
    for when, y, label, color in stages:
        ax.scatter([when], [0], s=65, zorder=3, color=color)
        ax.annotate(label, (when, 0), xytext=(0, 34 if y > 0 else -43), textcoords="offset points", ha="center", fontsize=9, color=color)
    ax.text(x0 + timedelta(minutes=0.4), 0.32, "Contest literal 10:30: stage and timezone unresolved; retained separately", color="#7c3aed", fontsize=9)
    ax.set_xlim(x0, x1)
    ax.set_ylim(-0.38, 0.48)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=onset.tzinfo))
    ax.set_xlabel("Beijing time (UTC+08:00); original timestamp accuracy is unquantified")
    ax.set_title("Event evidence and process-phase timing — no calibrated 95% interval")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(OUT_path, dpi=180)
    plt.close(fig)


def _build_spatial_outputs(
    trajectories: pd.DataFrame,
    arrivals: pd.DataFrame,
    event_summary: dict,
    event_gpkg: Path,
    gpkg_path: Path,
    png_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    route_frame = gpd.read_file(event_gpkg, layer="event_routes_A_B").to_crs(CRS)
    reference_points = gpd.read_file(event_gpkg, layer="reference_points").to_crs(CRS)
    unesco = gpd.read_file(event_gpkg, layer="unesco_mapped_extent").to_crs(CRS)
    unosat = gpd.read_file(event_gpkg, layer="unosat_mapped_extent").to_crs(CRS)
    detachment = gpd.read_file(event_gpkg, layer="unosat_detachment_zone").to_crs(CRS)

    traj = trajectories.copy()
    traj["time_beijing"] = pd.to_datetime(traj["time_beijing"], utc=True).dt.tz_convert("Asia/Shanghai")
    traj_rows = []
    for (route_id, scenario), group in traj.groupby(["route_id", "scenario"], sort=False):
        group = group.sort_values("seconds_after_reported_onset")
        xy = list(zip(group.x_utm45.astype(float), group.y_utm45.astype(float)))
        if len(xy) < 2:
            continue
        route_arrival = arrivals.loc[arrivals.route_id.eq(route_id) & arrivals.scenario.eq(scenario)].iloc[0]
        traj_rows.append({
            "route_id": route_id, "scenario": scenario, "speed_factor": float(route_arrival.speed_factor),
            "travel_time_min": float(route_arrival.travel_time_min),
            "scenario_arrival_time": route_arrival.arrival_if_started_1052,
            "matches_reported_arrival_by_construction": bool(route_arrival.matches_1059_by_construction),
            "source_data_role": "Q4 1D kinematic trajectory; event-anchored sensitivity, not observation",
            "geometry": LineString(xy),
        })
    trajectory_lines = gpd.GeoDataFrame(traj_rows, geometry="geometry", crs=CRS)

    arrival_rows = []
    for row in arrivals.itertuples():
        route = route_frame.loc[route_frame.route_id.eq(row.route_id)].iloc[0]
        point = route.geometry.interpolate(route.geometry.length)
        arrival_rows.append({
            "route_id": row.route_id, "scenario": row.scenario, "predicted_arrival_time": row.arrival_if_started_1052,
            "travel_time_min": float(row.travel_time_min), "speed_factor": float(row.speed_factor),
            "is_statistical_interval": False, "baseline_matches_anchor_by_construction": bool(row.matches_1059_by_construction),
            "geometry": point,
        })
    arrival_points = gpd.GeoDataFrame(arrival_rows, geometry="geometry", crs=CRS)

    # Satellite interpretations are kept as separately named reference layers.
    for frame, role in ((unesco, "UNESCO satellite-interpreted cumulative extent; comparison only"),
                        (unosat, "UNOSAT satellite-interpreted cumulative extent; comparison only"),
                        (detachment, "UNOSAT detachment zone; comparison only")):
        frame["comparison_role"] = role
    route_frame["comparison_role"] = "candidate centerline route, not a surveyed flow path"
    first = True
    _write_layer(gpkg_path, route_frame, "candidate_routes_A_B", first=first); first = False
    for frame, layer in ((reference_points, "reference_points"), (trajectory_lines, "scenario_front_trajectories"),
                         (arrival_points, "conditional_port_arrival_points"), (unesco, "unesco_extent_comparison"),
                         (unosat, "unosat_extent_comparison"), (detachment, "unosat_detachment_comparison")):
        _write_layer(gpkg_path, frame, layer, first=first)
        first = False

    distance_rows = []
    route_candidates = {row["route_id"]: row for row in event_summary["route_candidates"]}
    for route_id, route in route_candidates.items():
        distance_rows.append({
            "record_type": "candidate_centerline_route", "route_id": route_id, "scenario": None,
            "distance_km": float(route["centerline_distance_km"]), "distance_lower_km": None, "distance_upper_km": None,
            "source_chainage_km": float(route["source_chainage_km"]), "port_chainage_km": float(route["port_chainage_km"]),
            "source_lateral_offset_m": float(route["source_offset_m"]), "port_lateral_offset_m": float(route["port_offset_m"]),
            "mean_grade_pct": float(route["mean_grade_pct"]), "mapped_area_km2": None,
            "mapped_extent": None, "status": "centerline projection distance; source point is not a surveyed boundary or flow path",
        })
    area_map = event_summary.get("mapped_extent_geometry_area_km2", {})
    containment = event_summary.get("mapped_extent_contains_reference_points", {})
    for extent_name, area_key in (("unesco_mapped_extent", "unesco_mapped_extent"), ("unosat_mapped_extent", "unosat_mapped_extent")):
        contains = containment.get(extent_name, {})
        distance_rows.append({
            "record_type": "satellite_interpreted_extent_comparison", "route_id": None, "scenario": None,
            "distance_km": None, "distance_lower_km": None, "distance_upper_km": None,
            "source_chainage_km": None, "port_chainage_km": None, "source_lateral_offset_m": None,
            "port_lateral_offset_m": None, "mean_grade_pct": None,
            "mapped_area_km2": area_map.get(area_key), "mapped_extent": extent_name,
            "source_A_inside": contains.get("source_A"), "source_B_inside": contains.get("source_B"),
            "port_core_inside": contains.get("port_core"),
            "status": "same-event satellite interpretation; plotted separately, not a predictive footprint or independent validation",
        })
    distances = pd.DataFrame(distance_rows)

    fig, axes = plt.subplots(1, 2, figsize=(16, 8), constrained_layout=True)
    route_bounds = route_frame.total_bounds
    def draw_context(ax):
        unesco.boundary.plot(ax=ax, color="#f59e0b", linewidth=1.0, label="UNESCO extent (comparison)")
        unosat.boundary.plot(ax=ax, color="#dc2626", linewidth=0.9, label="UNOSAT extent (comparison)")
        detachment.boundary.plot(ax=ax, color="#7c3aed", linewidth=1.2, label="UNOSAT detachment (comparison)")
        route_frame.loc[route_frame.route_id.eq("source_A")].plot(ax=ax, color="#2563eb", linewidth=2.1, label="A route")
        route_frame.loc[route_frame.route_id.eq("source_B")].plot(ax=ax, color="#0891b2", linewidth=1.5, linestyle="--", label="B route")
        reference_points.plot(ax=ax, color="#111827", markersize=27, edgecolor="white", linewidth=0.6, label="Reference points")
        for ref in reference_points.itertuples():
            name = getattr(ref, "site_id", "reference")
            ax.annotate(str(name), (ref.geometry.x, ref.geometry.y), xytext=(4, 4), textcoords="offset points", fontsize=7)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(alpha=0.2)
    draw_context(axes[0])
    axes[0].set_title("Regional overview\nSatellite interpretations are context only")
    axes[0].legend(fontsize=7, loc="best")
    draw_context(axes[1])
    axes[1].set_xlim(route_bounds[0] - 1200, route_bounds[2] + 1200)
    axes[1].set_ylim(route_bounds[1] - 1200, route_bounds[3] + 1200)
    axes[1].set_title("Route detail\nTransition markers are constant-speed model positions")
    axes[1].legend(fontsize=7, loc="best")
    baseline = traj.loc[traj.scenario.eq("event_anchored_baseline")]
    for seconds, marker, label in ((140, "^", "10:54:19 phase; nearest 5s model sample"), (190, "s", "10:55:10 phase; nearest 5s model sample")):
        for route_id, group in baseline.groupby("route_id"):
            idx = (group.seconds_after_reported_onset.astype(float) - seconds).abs().idxmin()
            point = group.loc[idx]
            axes[1].scatter(float(point.x_utm45), float(point.y_utm45), marker=marker, s=45, edgecolor="black", linewidth=0.4, label=label if route_id == "source_A" else None, zorder=5)
    axes[1].legend(fontsize=7, loc="best")
    for ax in axes:
        ax.set_xlabel("UTM 45N easting (m)")
        ax.set_ylabel("UTM 45N northing (m)")
    fig.suptitle("Conditional centerline routes vs separate UNESCO/UNOSAT extents")
    fig.savefig(png_path, dpi=180)
    plt.close(fig)
    return distances, traj


def main() -> None:
    _require_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        path = OUT / name
        if path.exists():
            path.unlink()

    q3_cfg = json.loads(Q3_CONFIG.read_text(encoding="utf-8"))
    q4_cfg = json.loads(Q4_CONFIG.read_text(encoding="utf-8"))
    event_summary = json.loads(EVENT_SUMMARY.read_text(encoding="utf-8"))
    onset = parse_aware_datetime(q3_cfg["ice_collapse_onset"])
    transition_start = parse_aware_datetime(q3_cfg["debris_to_mudflow_transition_start"])
    transition_end = parse_aware_datetime(q3_cfg["debris_to_mudflow_transition_end"])
    transition_rep = parse_aware_datetime(q3_cfg["transition_representative_time"])
    arrival = parse_aware_datetime(q3_cfg["arrival_at_port"])
    initialization = parse_aware_datetime(q3_cfg["forecast_initialization_utc"])
    validate_event_chronology(onset, transition_start, transition_end, arrival)

    event_evidence = _event_evidence(q3_cfg, initialization)
    weather = pd.read_csv(Q2_FINAL / "dynamic_weather_context.csv")
    time_scales = pd.read_csv(Q2_FINAL / "temporal_reliability.csv")
    forecast_assumptions = _forecast_assumptions(weather, time_scales, initialization, q3_cfg)
    intervals = pd.DataFrame(build_trigger_intervals(onset, transition_start, transition_end, arrival))
    speed_factors = {name: float(value) for name, value in q4_cfg["scenario_speed_factors"].items()}
    scenario_rows = arrival_scenarios(event_summary["route_candidates"], onset, arrival, speed_factors)
    q4_arrivals = pd.read_csv(Q4_OUT / "question4_arrival_sensitivity.csv")
    q4_trajectories = pd.read_csv(Q4_OUT / "question4_front_trajectories.csv")
    q4_transition_positions = pd.read_csv(Q4_OUT / "question4_transition_positions.csv")
    scenario_frame = pd.DataFrame(scenario_rows)
    for row in scenario_frame.itertuples():
        matching = q4_arrivals.loc[q4_arrivals.route_id.eq(row.route_id) & q4_arrivals.scenario.eq(row.scenario)]
        if matching.empty:
            raise ValueError(f"Question 4 scenario missing for {row.route_id}/{row.scenario}")
        if not math.isclose(float(matching.iloc[0].centerline_distance_km), float(row.centerline_distance_km), abs_tol=1e-5):
            raise ValueError(f"Q3/Q4 route-distance mismatch for {row.route_id}/{row.scenario}")
    scenario_frame = scenario_frame.merge(
        q4_arrivals[["route_id", "scenario", "centerline_source_z_m", "centerline_port_z_m", "mean_grade_pct", "arrival_if_started_1052", "matches_1059_by_construction"]],
        on=["route_id", "scenario"], how="left", validate="one_to_one",
    )
    scenario_frame["arrival_time_bjt"] = scenario_frame["predicted_arrival_time"]
    scenario_frame["arrival_matches_reported_by_construction"] = scenario_frame["arrival_matches_anchor_by_construction"]
    scenario_frame["warning_status"] = "hypothetical immediate source detection; not an issued warning"

    # Hourly/minute reporting precision is represented as explicit deterministic
    # tolerance scenarios, never as a confidence interval or probability model.
    sensitivity = _timestamp_sensitivity(onset, transition_start, transition_end, arrival)
    for route in event_summary["route_candidates"]:
        group = scenario_frame.loc[scenario_frame.route_id.eq(route["route_id"])]
        for row in group.itertuples():
            sensitivity.loc[len(sensitivity)] = {
                "experiment": "route_and_speed_sensitivity", "target": route["route_id"],
                "scenario": row.scenario, "endpoint_tolerance_seconds": None,
                "reference_elapsed_seconds": row.travel_time_seconds,
                "lower_elapsed_seconds": row.travel_time_seconds, "upper_elapsed_seconds": row.travel_time_seconds,
                "is_probability_interval": False,
                "assumption": f"{row.speed_factor:g}x of event-anchored route-average speed; no statistical distribution; arrival anchor leakage retained",
            }

    # Warning leads: initialization lag is historical chronology, while actual
    # issue/publication times and true operational lead remain null.
    gfs_cycle = forecast_timing(initialization, onset, publication_time=None)
    lead_rows = []
    for model in ("GFS 0.25-degree forecast", "WRF d01 model"):
        for target, target_time in (("ice_rock_avalanche_onset", onset), ("transition_phase_start", transition_start),
                                    ("transition_representative_scenario", transition_rep),
                                    ("transition_phase_end", transition_end), ("reported_port_arrival", arrival)):
            lead_rows.append({
                "lead_type": "model_initialization_to_event_time_difference", "model": model,
                "reference_time": initialization.isoformat(), "target_stage": target,
                "target_time": target_time.isoformat(),
                "minutes": (target_time - initialization).total_seconds() / 60,
                "modeled_publication_time": None, "actual_warning_issue_time": None,
                "operational_warning_lead_minutes": None, "scenario_status": "retrospective initialization lag; not operational warning lead",
            })
    for row in scenario_frame.itertuples():
        lead_rows.append({
            "lead_type": "conditional_source_detection_to_port_arrival", "model": "Q4 1D centerline speed scenario",
            "reference_time": onset.isoformat(), "target_time": row.predicted_arrival_time,
            "minutes": row.conditional_detection_to_arrival_lead_seconds / 60,
            "modeled_publication_time": None, "actual_warning_issue_time": None,
            "operational_warning_lead_minutes": None,
            "route_id": row.route_id, "scenario": row.scenario,
            "scenario_status": "hypothetical immediate upstream ice-collapse detection at reported onset; conditional lead only; event-anchored speeds are retrospective",
        })
    lead_rows.append({
        "lead_type": "actual_operational_warning_lead", "model": "not available",
        "reference_time": None, "target_time": arrival.isoformat(), "minutes": None,
        "modeled_publication_time": None, "actual_warning_issue_time": None,
        "operational_warning_lead_minutes": None,
        "scenario_status": "not estimable: no historical public-availability timestamp or signed warning issue time",
    })
    warning_leads = pd.DataFrame(lead_rows)

    # Time-precision sensitivity only widens deterministic bounds; it assigns no mass.
    chain_compatible = transition_start >= onset and transition_end <= arrival
    validation_rows = [
        {"check": "reported_transition_within_conditional_event_chain_bound", "result": bool(chain_compatible), "empirical_coverage_rate": None, "n_independent_trigger_labels": 0, "interpretation": "Chronological compatibility only; not validation of a 95% interval."},
        {"check": "nominal_95_trigger_interval_estimable", "result": False, "empirical_coverage_rate": None, "n_independent_trigger_labels": 0, "interpretation": "No defensible error distribution and no independent reliable trigger labels; interval remains null."},
        {"check": "event_anchored_speed_independent_of_reported_arrival", "result": False, "empirical_coverage_rate": None, "n_independent_trigger_labels": 0, "interpretation": "Q4 baseline speed is route distance divided by reported 10:52-to-10:59 time; matching 10:59 is by construction and not independent prediction accuracy."},
        {"check": "satellite_extent_independent_validation", "result": False, "empirical_coverage_rate": None, "n_independent_trigger_labels": 0, "interpretation": "UNESCO/UNOSAT extents depict the same event; retained only as separate visual/spatial comparisons and not used to tune the model."},
        {"check": "calibration_validation_split_available", "result": False, "empirical_coverage_rate": None, "n_independent_trigger_labels": 0, "interpretation": "One event timeline and no independent event set; no event-level holdout or empirical interval coverage can be computed."},
    ]
    interval_validation = pd.DataFrame(validation_rows)

    front_trajectories = q4_trajectories.copy()
    front_trajectories["coordinate_status"] = "model-sampled centerline front coordinate; not an observed trajectory"
    front_trajectories["time_resolution_status"] = "5-second kinematic output step; not 5-second observation or trigger-time precision"

    gpkg_path = OUT / "question3_spatial_scenarios.gpkg"
    distances, front_lines = _build_spatial_outputs(
        front_trajectories, q4_arrivals, event_summary, EVENT_GPKG, gpkg_path,
        OUT / "question3_spatial_map.png",
    )
    event_evidence.to_csv(OUT / "event_time_evidence.csv", index=False)
    forecast_assumptions.to_csv(OUT / "forecast_assumptions.csv", index=False)
    intervals.to_csv(OUT / "trigger_time_intervals.csv", index=False)
    warning_leads.to_csv(OUT / "warning_lead_times.csv", index=False)
    interval_validation.to_csv(OUT / "interval_validation.csv", index=False)
    distances.to_csv(OUT / "spatial_distance_range.csv", index=False)
    scenario_frame.to_csv(OUT / "q3_arrival_scenarios.csv", index=False)
    front_trajectories.to_csv(OUT / "q3_front_trajectories.csv", index=False)
    sensitivity.to_csv(OUT / "question3_sensitivity.csv", index=False)
    _plot_timeline(OUT / "question3_timeline.png", onset, transition_start, transition_end, arrival, q3_cfg.get("contest_literal_time", "10:30"))

    init_to_onset = forecast_timing(initialization, onset, publication_time=None)
    speed_range = {
        "minimum_scenario_arrival": min(scenario_frame.predicted_arrival_time),
        "maximum_scenario_arrival": max(scenario_frame.predicted_arrival_time),
        "minimum_speed_factor": min(speed_factors.values()),
        "maximum_speed_factor": max(speed_factors.values()),
        "interpretation": "Deterministic sensitivity envelope only; not a nominal 95% prediction interval.",
    }
    summary = {
        "question": 3,
        "status": "technical baseline completed; pre-event operational prediction and calibrated trigger-time uncertainty unavailable",
        "forecast_feasibility": {
            "model_initialization_utc": initialization.isoformat(),
            "generation_time_utc": None,
            "public_availability_time_utc": None,
            "historical_warning_issue_time": None,
            "initialization_to_reported_onset_hours": init_to_onset["initialization_to_event_hours"],
            "operational_lead_time": None,
            "conclusion": "Downloaded GFS/WRF values have initialization and valid timestamps, but generation/public-availability metadata is absent. WRF d01 cannot be called an operational pre-event warning; forecast issue/public time for GFS is also not evidenced locally.",
            "weather_resolution": {"GFS": "6 h / 0.25 degree", "WRF d01": "1 h / approximately 9.014 km"},
            "no_subhourly_interpolation": True,
        },
        "event_time_evidence": {
            "ice_rock_onset": onset.isoformat(), "transition_phase": [transition_start.isoformat(), transition_end.isoformat()],
            "transition_representative_scenario_time": transition_rep.isoformat(), "physical_trigger": None,
            "port_arrival": arrival.isoformat(), "contest_literal_time": q3_cfg.get("contest_literal_time"),
            "timezone": "Asia/Shanghai UTC+08:00 for user timeline; contest timezone unresolved",
            "evidence_file": "event_time_evidence.csv",
        },
        "trigger_time": {
            "conditional_event_chain_bound": [onset.isoformat(), arrival.isoformat()],
            "reported_transition_phase_not_trigger": [transition_start.isoformat(), transition_end.isoformat()],
            "nominal_95_prediction_interval": None,
            "empirical_coverage_rate": None,
            "reason": "No independent precise physical trigger labels and no defensible calibrated time-error distribution.",
        },
        "conditional_event_detection_forecast": {
            "detection_scenario": "hypothetical upstream ice-collapse detection at reported 10:52 BJT with zero processing delay",
            "arrival_sensitivity_envelope": speed_range,
            "speed_source": "Q4 config factors 0.85/1.00/1.15 around speed derived from reported onset and 10:59 arrival",
            "baseline_match_is_by_construction": True,
            "warning_issue_time": None,
            "actual_operational_warning_lead": None,
        },
        "spatial_distances": {
            "route_distance_range_km": [float(distances.loc[distances.record_type.eq("candidate_centerline_route"), "distance_km"].min()), float(distances.loc[distances.record_type.eq("candidate_centerline_route"), "distance_km"].max())],
            "q4_front_resolution_seconds": 5,
            "front_coordinates": "q3_front_trajectories.csv and GeoPackage layer scenario_front_trajectories",
            "satellite_extents_are_separate_comparisons": True,
        },
        "validation_and_leakage": {
            "independent_trigger_labels": 0,
            "empirical_95_interval_coverage_rate": None,
            "event_arrival_used_to_derive_baseline_speed": True,
            "same_event_satellite_extents_used_as_independent_validation": False,
            "details": "interval_validation.csv",
        },
        "input_files": {
            "question2_dynamic_weather": "output/question2/final/dynamic_weather_context.csv",
            "question2_temporal_scale": "output/question2/final/temporal_reliability.csv",
            "question3_config": "config/question3-scenario.json",
            "question4_config": "config/question4-kinematic.json",
            "event_context": "output/event_context/event_context_summary.json",
            "question4_trajectories": "output/question4/question4_front_trajectories.csv",
        },
        "raw_data_modified": False,
        "all_output_paths_relative_to_repository": True,
        "unmet_requirements": [
            "No operational GFS/WRF generation/publication timestamp or historical warning issuance record.",
            "Exact debris-flow physical trigger time and original timestamp evidence/measurement error are missing.",
            "No defensible uncertainty distribution or independent events for nominal 95% prediction interval and empirical coverage.",
            "No measured propagation speed; scenario speeds are event-anchored and leak the reported arrival.",
            "No independently surveyed georeferenced flow boundary; satellite interpretations are same-event comparisons.",
        ],
        "created_at_local": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
    }
    (OUT / "question3_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# 第三问技术版：时间可预报性、条件到达情景与空间范围

## 复现

在项目根目录的`mc-base`环境依次运行：

```powershell
python scripts/prepare_event_context.py
python scripts/prepare_question2_layers.py
python scripts/build_question2_assessment.py
python scripts/build_question4_kinematic.py
python scripts/build_question3_forecast.py
```

最后一个入口只写`output/question3/final/`，不改写Q2或Q4结果。路径由脚本定位仓库根目录；原始数据保持只读。

## 结论口径

- 10:52冰岩崩起始、10:54:19–10:55:10碎屑流向泥石流转化阶段、10:59口岸到达均按用户提供的北京时间记录；10:30赛题字样保留，时区和事件阶段未明。泥石流物理触发时刻未知。
- 赛题所需的**名义95%触发时间预测区间和经验覆盖率不可估计**。没有多起独立、精确的触发时间标签，也没有校准后的误差分布。条件区间/转化过程窗口不是置信区间。
- GFS/WRF已知起报与有效时刻，但本地文件没有生成时间、公开可得时间或实际预警签发记录。初始化到事件的时间差是回溯间隔，不能说成业务提前量。GFS 6小时、WRF d01逐小时，均不插值为秒级降雨。
- 假设在10:52检测到上游冰岩崩且零处理延迟，复用Q4的中心线平均速度情景，A/B路线产生条件到达时间约10:58:05–11:00:14。±15%速度因子沿用Q4配置，仅为敏感性；基准速度使用10:59报告到达反算，故基准命中10:59是由构造造成，所有结果均非独立预测准确率或95%区间。
- A/B中心线投影距离约22.156/21.993 km。UNESCO与UNOSAT卫星判读范围分别保留为独立图层；它们描述同一事件，不作为独立验证真值。

## 文件

`event_time_evidence.csv`记录阶段、时区、来源、精度与证据等级；`forecast_assumptions.csv`列出模式初始化/有效时刻及缺失的生成、公开时间；`trigger_time_intervals.csv`区分条件时间约束、过程阶段和不可估计的95%区间；`warning_lead_times.csv`区分初始化回溯差、条件检测提前量及未知的真实签发提前量；`interval_validation.csv`记录覆盖率不可估计和信息泄漏检查。

`q3_arrival_scenarios.csv`为A/B×速度情景摘要；`q3_front_trajectories.csv`为5秒步长的带坐标模拟前锋，5秒是模拟输出采样间距，不是观测精度。`question3_spatial_scenarios.gpkg`可在QGIS打开，包含候选路线、情景传播轨迹、条件到达点、A/B/口岸参考点，以及分开的UNESCO、UNOSAT累计范围和UNOSAT脱离区。`spatial_distance_range.csv`记录中心线距离与卫星范围面积/参考点包含状态。两张PNG分别展示时间证据和空间情景。

敏感性位于`question3_sensitivity.csv`：0.85/1.00/1.15速度情景来自现有Q4配置；分钟/秒时间戳误差情景是明确标注的端点容差假设，不包含概率分布，不称95%区间。
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    _plot_timeline(OUT / "question3_timeline.png", onset, transition_start, transition_end, arrival, q3_cfg.get("contest_literal_time", "10:30"))
    absent = [name for name in OUTPUTS if not (OUT / name).is_file() or (OUT / name).stat().st_size == 0]
    if absent:
        raise RuntimeError("Required Question 3 outputs missing or empty: " + ", ".join(absent))
    layers = gpd.list_layers(gpkg_path)
    if len(layers) != 7:
        raise RuntimeError(f"Expected 7 readable spatial layers, found {len(layers)}")
    print(json.dumps({"output": OUT.relative_to(ROOT).as_posix(), "files": OUTPUTS, "gpkg_layers": layers.to_dict(orient="records"), "scenario_rows": len(scenario_frame), "trajectory_rows": len(front_trajectories), "nominal_95_interval": None, "empirical_coverage": None, "raw_data_modified": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
