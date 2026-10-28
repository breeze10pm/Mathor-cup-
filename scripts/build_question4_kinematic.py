"""Build a georeferenced, event-anchored 1D kinematic route scenario.

This is a transparent path/arrival-time simulation, not a depth-averaged
hydrodynamic or rheological debris-flow model.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "question4-kinematic.json"
EVENT = ROOT / "output" / "event_context" / "event_context_summary.json"
CENTERLINE = ROOT / "data" / "supplementary" / "geo-pera-v1.1" / "centerline_v2.csv"
BUDGET = ROOT / "data" / "supplementary" / "geo-pera-v1.1" / "bhotekoshi_sediment-budget_per-km.csv"
OUT = ROOT / "output" / "question4"
CRS = "EPSG:32645"


def main() -> None:
    for path in (EVENT, CENTERLINE, BUDGET):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path.relative_to(ROOT)}; first run scripts/prepare_event_context.py"
            )
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    event = json.loads(EVENT.read_text(encoding="utf-8"))
    centerline = pd.read_csv(CENTERLINE).sort_values("chainage_m")
    routes = event["route_candidates"]
    start_time = datetime.fromisoformat(cfg["start_time"])
    reported_arrival = datetime.fromisoformat(cfg["arrival_anchor_time"])
    observed_elapsed_s = (reported_arrival - start_time).total_seconds()
    if observed_elapsed_s <= 0:
        raise ValueError("Reported chronology must be ordered")

    step_s = int(cfg["time_step_seconds"])
    factors = {k: float(v) for k, v in cfg["scenario_speed_factors"].items()}
    trajectory_rows: list[dict[str, object]] = []
    arrival_rows: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []
    for route in routes:
        start_km = float(route["source_chainage_km"])
        end_km = float(route["port_chainage_km"])
        distance_m = float(route["centerline_distance_km"]) * 1000
        local = centerline.loc[
            centerline.chainage_m.between(start_km * 1000, end_km * 1000)
        ].copy()
        if len(local) < 2:
            raise ValueError(f"Too few centerline vertices for {route['route_id']}")
        # CSV chainage values are integer meters; exact nearest-point projections
        # can be fractional, so widen before adding interpolated route endpoints.
        local["chainage_m"] = local["chainage_m"].astype("float64")
        # Preserve the measured centerline elevations and add exact route endpoints.
        for chainage_m in (start_km * 1000, end_km * 1000):
            if not np.isclose(local.chainage_m, chainage_m).any():
                local.loc[len(local)] = {
                    "chainage_m": chainage_m,
                    "x_utm45": np.interp(chainage_m, centerline.chainage_m, centerline.x_utm45),
                    "y_utm45": np.interp(chainage_m, centerline.chainage_m, centerline.y_utm45),
                    "lon": np.interp(chainage_m, centerline.chainage_m, centerline.lon),
                    "lat": np.interp(chainage_m, centerline.chainage_m, centerline.lat),
                    "elev_m": np.interp(chainage_m, centerline.chainage_m, centerline.elev_m),
                }
        local = local.sort_values("chainage_m")
        local.insert(0, "route_id", route["route_id"])
        local["evidence"] = "public centerline; elevation datum/measurement uncertainty not supplied in CSV"
        profile_rows.extend(local.to_dict(orient="records"))

        base_speed = distance_m / observed_elapsed_s
        for scenario, factor in factors.items():
            speed = base_speed * factor
            travel_s = distance_m / speed
            arrival = start_time + timedelta(seconds=travel_s)
            arrival_rows.append(
                {
                    "route_id": route["route_id"],
                    "scenario": scenario,
                    "speed_factor": factor,
                    "centerline_distance_km": distance_m / 1000,
                    "apparent_speed_m_s": speed,
                    "centerline_source_z_m": route["centerline_source_z_m"],
                    "centerline_port_z_m": route["centerline_port_z_m"],
                    "mean_grade_pct": route["mean_grade_pct"],
                    "travel_time_min": travel_s / 60,
                    "arrival_if_started_1052": arrival.isoformat(),
                    "matches_1059_by_construction": bool(scenario == "event_anchored_baseline"),
                    "interval_is_statistical": False,
                }
            )
            times = np.arange(0, int(np.ceil(travel_s)) + step_s, step_s)
            for elapsed in times:
                chainage_m = min(start_km * 1000 + speed * float(elapsed), end_km * 1000)
                x = float(np.interp(chainage_m, local.chainage_m, local.x_utm45))
                y = float(np.interp(chainage_m, local.chainage_m, local.y_utm45))
                z = float(np.interp(chainage_m, local.chainage_m, local.elev_m))
                trajectory_rows.append(
                    {
                        "route_id": route["route_id"],
                        "scenario": scenario,
                        "seconds_after_reported_onset": int(elapsed),
                        "time_beijing": (start_time + timedelta(seconds=int(elapsed))).isoformat(),
                        "chainage_km": chainage_m / 1000,
                        "distance_from_projected_source_km": (chainage_m - start_km * 1000) / 1000,
                        "elevation_m_from_centerline": z,
                        "remaining_km": max(0.0, (end_km * 1000 - chainage_m) / 1000),
                        "front_reached_port": bool(chainage_m >= end_km * 1000),
                        "x_utm45": x,
                        "y_utm45": y,
                    }
                )

    trajectories = pd.DataFrame(trajectory_rows)
    arrivals = pd.DataFrame(arrival_rows)
    profile = pd.DataFrame(profile_rows).drop_duplicates(["route_id", "chainage_m"])
    trajectories.to_csv(OUT / "question4_front_trajectories.csv", index=False)
    arrivals.to_csv(OUT / "question4_arrival_sensitivity.csv", index=False)
    profile.to_csv(OUT / "question4_route_profile.csv", index=False)

    budget = pd.read_csv(BUDGET)
    local_budget = budget.loc[budget.reach.eq("A") & budget.km.between(19.5, 29.5)].copy()
    local_budget.to_csv(OUT / "question4_local_sediment_budget.csv", index=False)
    near_core = budget.loc[budget.reach.eq("A") & budget.km.isin([23.75, 24.25])]

    # Only the centerline samples that intersect the measured-change raster are
    # available in the profile; the full per-km floor-masked budget is reported separately.
    event_profile = pd.read_csv(ROOT / "output" / "event_context" / "centerline_event_profile.csv")
    valid_dh = event_profile.dh_m.dropna()
    summary = {
        "question": 4,
        "model": "georeferenced centerline 1D event-anchored kinematic scenario",
        "status": "terrain-positioned and visually mapped; not a calibrated depth-averaged or rheological simulation",
        "reported_start_time": start_time.isoformat(),
        "reported_arrival_time": reported_arrival.isoformat(),
        "reported_elapsed_minutes": observed_elapsed_s / 60,
        "source_to_port_routes": routes,
        "sensitivity_factors": factors,
        "scenario_arrivals": arrivals.to_dict(orient="records"),
        "local_v11_change_profile": {
            "valid_centerline_samples": int(valid_dh.size),
            "total_centerline_samples": int(len(event_profile)),
            "median_dh_m": float(valid_dh.median()) if valid_dh.size else None,
            "interpretation": "sparse sampled elevation change only; not a deposition thickness estimate",
        },
        "v11_floor_budget_near_port_core": near_core.to_dict(orient="records"),
        "datum_and_coverage": "v1.1 dh is EGM2008 and measured-only; local 2019/2026 DEM products use ellipsoidal heights. Do not directly difference these grids.",
        "omitted_physics": cfg["omitted_or_unknown"],
        "interpretation": "Distance/route/elevation now come from the public georeferenced centerline. Event-anchored speed still uses user-reported onset and arrival and is not an independently observed flow velocity.",
    }
    (OUT / "question4_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Georeferenced map panel and time-distance-elevation scenario panels.
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6), constrained_layout=True)
    points = gpd.read_file(ROOT / "output" / "event_context" / "event_context.gpkg", layer="reference_points")
    mapped_unesco = gpd.read_file(ROOT / "output" / "event_context" / "event_context.gpkg", layer="unesco_mapped_extent")
    mapped_unosat = gpd.read_file(ROOT / "output" / "event_context" / "event_context.gpkg", layer="unosat_mapped_extent")
    route_layer = gpd.read_file(ROOT / "output" / "event_context" / "event_context.gpkg", layer="event_routes_A_B")
    mapped_unesco.boundary.plot(ax=axes[0], color="#9ca3af", linewidth=0.6, label="UNESCO/IHP-WINS extent")
    mapped_unosat.boundary.plot(ax=axes[0], color="#a855f7", linewidth=0.7, label="UNOSAT GDB extent")
    for row in route_layer.itertuples():
        gpd.GeoSeries([row.geometry], crs=route_layer.crs).plot(
            ax=axes[0], color="#2563eb" if row.route_id == "source_A" else "#d97706", linewidth=1.7,
            label=f"Centerline route {row.route_id}",
        )
    for row in points.itertuples():
        color = {"source_A": "#2563eb", "source_B": "#d97706", "port_core": "#dc2626"}[row.site_id]
        axes[0].scatter(row.geometry.x, row.geometry.y, color=color, edgecolor="white", s=42, zorder=4)
        label_offset = {"source_A": (5, -12), "source_B": (5, 8), "port_core": (5, 6)}[row.site_id]
        axes[0].annotate(row.site_id, (row.geometry.x, row.geometry.y), xytext=label_offset, textcoords="offset points", fontsize=8)
    axes[0].set_title("Mapped extent and candidate source-to-port routes")
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].set_xlabel("Easting (m, UTM 45N)")
    axes[0].set_ylabel("Northing (m, UTM 45N)")
    axes[0].grid(alpha=0.2)
    axes[0].legend(fontsize=7, loc="best")

    palette = {"slow_sensitivity": "#3B82F6", "event_anchored_baseline": "#111827", "fast_sensitivity": "#D97706"}
    for (route_id, scenario), part in trajectories.groupby(["route_id", "scenario"], sort=False):
        axes[1].plot(
            part.seconds_after_reported_onset / 60,
            part.distance_from_projected_source_km,
            color=palette[scenario], linestyle="-" if route_id == "source_A" else "--",
            linewidth=2 if scenario == "event_anchored_baseline" else 1.25,
            label=f"{route_id} / {scenario}",
        )
    axes[1].axvline(7, color="#dc2626", linestyle=":", linewidth=1.2, label="Reported port arrival (10:59)")
    axes[1].set(xlabel="Minutes after reported ice-collapse onset (10:52 BJT)", ylabel="Distance from source projection (km)")
    axes[1].set_title("Centerline-based arrival sensitivity")
    axes[1].grid(alpha=0.22)
    axes[1].legend(fontsize=6.5, ncol=2, loc="lower right")
    fig.savefig(OUT / "question4_georeferenced_scenarios.png", dpi=180)
    plt.close(fig)
    print(json.dumps({"routes": routes, "budget_rows_near_core": near_core.to_dict(orient="records"), "v11_valid_profile_samples": int(valid_dh.size)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
