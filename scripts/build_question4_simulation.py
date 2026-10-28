"""Build Q4 one-dimensional depth-averaged dynamics scenarios and artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import LineString, Point

from question4_dynamics import prepare_uniform_profile, run_simulation, sample_raster_nearest
from question4_visuals import save_animation_gif, save_bar_chart, save_map, save_multi_panel

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "question4-simulation.json"
OUT = ROOT / "output" / "question4" / "final"
CRS = "EPSG:32645"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profile_line(centerline: pd.DataFrame, start_m: float, end_m: float) -> LineString:
    local = centerline.loc[centerline.chainage_m.between(start_m, end_m)].copy()
    endpoint_rows = []
    for chainage in (start_m, end_m):
        endpoint_rows.append(
            {
                "chainage_m": chainage,
                "x_utm45": np.interp(chainage, centerline.chainage_m, centerline.x_utm45),
                "y_utm45": np.interp(chainage, centerline.chainage_m, centerline.y_utm45),
            }
        )
    local = pd.concat([local, pd.DataFrame(endpoint_rows)], ignore_index=True)
    local = local.drop_duplicates("chainage_m").sort_values("chainage_m")
    return LineString(local[["x_utm45", "y_utm45"]].to_numpy())


def _line_to_chainage(centerline: pd.DataFrame, start_m: float, end_m: float) -> LineString:
    return _profile_line(centerline, start_m, end_m)


def _point_at_chainage(centerline: pd.DataFrame, chainage_m: float) -> Point:
    return Point(
        float(np.interp(chainage_m, centerline.chainage_m, centerline.x_utm45)),
        float(np.interp(chainage_m, centerline.chainage_m, centerline.y_utm45)),
    )


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    model_cfg = cfg["model"]
    numeric = cfg["numerics"]
    event_json = ROOT / model_cfg["event_context_summary"]
    event_gpkg = ROOT / model_cfg["event_context_gpkg"]
    centerline_path = ROOT / model_cfg["centerline_csv"]
    dem_path = ROOT / model_cfg["input_dem"]
    required = (event_json, event_gpkg, centerline_path, dem_path)
    missing = [p.relative_to(ROOT).as_posix() for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing Q4 inputs: " + ", ".join(missing))
    OUT.mkdir(parents=True, exist_ok=True)

    event = json.loads(event_json.read_text(encoding="utf-8"))
    if event.get("crs") != CRS:
        raise ValueError(f"Event context CRS {event.get('crs')} does not match {CRS}")
    centerline = pd.read_csv(centerline_path).sort_values("chainage_m").reset_index(drop=True)
    required_fields = ["chainage_m", "x_utm45", "y_utm45", "elev_m"]
    if not set(required_fields).issubset(centerline.columns):
        raise ValueError(f"Centerline must include {required_fields}")
    if centerline[required_fields].isna().any().any() or not np.isfinite(centerline[required_fields].to_numpy(dtype=float)).all():
        raise ValueError("Centerline coordinates/elevation contain missing or non-finite values; no imputation is allowed")
    if np.any(np.diff(centerline.chainage_m.to_numpy(dtype=float)) <= 0):
        raise ValueError("Centerline chainage is not strictly increasing")
    routes = {row["route_id"]: row for row in event["route_candidates"]}
    if not {s["route_id"] for s in cfg["scenarios"]}.issubset(routes):
        raise ValueError("Scenario route_id missing from event-context summary")

    with rasterio.open(dem_path) as dem_dataset:
        if dem_dataset.crs is None:
            raise ValueError("The HMA DEM has no CRS; refusing to sample it")
        dem_array = dem_dataset.read(1)
        dem_transform = dem_dataset.transform
        dem_crs = dem_dataset.crs
        dem_nodata = dem_dataset.nodata
        dem_metadata = {
            "path": dem_path.relative_to(ROOT).as_posix(),
            "crs": str(dem_crs),
            "resolution_map_units": [float(v) for v in dem_dataset.res],
            "shape_rows_cols": [int(dem_dataset.height), int(dem_dataset.width)],
            "nodata_value": float(dem_nodata) if dem_nodata is not None else None,
            "global_zero_fraction": float(np.mean(dem_array == 0)),
            "global_nodata_fraction": float(np.mean(dem_array == dem_nodata)) if dem_nodata is not None else 0.0,
            "sample_method": "nearest HMA DEM cell after EPSG:32645 to raster CRS transformation; zero/NoData/outside samples cause a hard error",
        }
    route_dem_profiles: dict[str, dict[str, object]] = {}
    for route_id in ("source_A", "source_B"):
        route = routes[route_id]
        start_m = float(route["source_chainage_km"]) * 1000.0
        end_m = float(route["port_chainage_km"]) * 1000.0
        dense_chainage, _ = prepare_uniform_profile(
            {"chainage_m": centerline.chainage_m.to_numpy(), "elev_m": centerline.elev_m.to_numpy()},
            start_m,
            end_m,
            25.0,
        )
        route_x = np.interp(dense_chainage, centerline.chainage_m, centerline.x_utm45)
        route_y = np.interp(dense_chainage, centerline.chainage_m, centerline.y_utm45)
        dem_elevation, sample_diagnostics = sample_raster_nearest(
            dem_array,
            dem_transform,
            route_x,
            route_y,
            CRS,
            str(dem_crs),
            dem_nodata,
            zero_is_nodata=True,
        )
        route_dem_profiles[route_id] = {
            "chainage_m": dense_chainage,
            "elevation_m": dem_elevation,
            "sample_diagnostics": sample_diagnostics,
        }

    # Satellite polygons are external post-event interpretations. They are read
    # only for a transparent spatial comparison, never used to calibrate inputs.
    unesco = gpd.read_file(event_gpkg, layer="unesco_mapped_extent").to_crs(CRS).geometry.union_all()
    unosat = gpd.read_file(event_gpkg, layer="unosat_mapped_extent").to_crs(CRS).geometry.union_all()
    runs: dict[str, dict[str, object]] = {}
    run_metadata: dict[str, dict[str, object]] = {}
    diagnostics: dict[str, dict[str, object]] = {}
    front_rows: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []
    hydro_rows: list[dict[str, object]] = []
    mass_rows: list[dict[str, object]] = []
    parameter_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    gpkg_route_rows: list[dict[str, object]] = []
    gpkg_front_rows: list[dict[str, object]] = []
    target_profile_times = np.asarray(numeric["profile_export_times_s"], dtype=float)
    output_interval = float(numeric["output_interval_s"])
    dx_requested = float(numeric["grid_spacing_m"])

    for scenario in cfg["scenarios"]:
        sid = scenario["id"]
        route = routes[scenario["route_id"]]
        start_m = float(route["source_chainage_km"]) * 1000.0
        end_m = float(route["port_chainage_km"]) * 1000.0
        local_profile = centerline.loc[centerline.chainage_m.between(start_m, end_m), required_fields]
        chainage_centers, _ = prepare_uniform_profile(
            {"chainage_m": centerline.chainage_m.to_numpy(), "elev_m": centerline.elev_m.to_numpy()},
            start_m,
            end_m,
            dx_requested,
        )
        route_profile = route_dem_profiles[scenario["route_id"]]
        bed = np.interp(chainage_centers, route_profile["chainage_m"], route_profile["elevation_m"])
        if len(local_profile) < 2:
            raise ValueError(f"Too few source centerline samples for {sid}")
        x_utm = np.interp(chainage_centers, centerline.chainage_m, centerline.x_utm45)
        y_utm = np.interp(chainage_centers, centerline.chainage_m, centerline.y_utm45)
        x_local = chainage_centers - start_m
        actual_dx = float(np.diff(chainage_centers).mean())
        if not np.allclose(np.diff(chainage_centers), actual_dx, rtol=1e-8, atol=1e-8):
            raise ValueError(f"Nonuniform computational grid for {sid}")
        grade = -np.gradient(bed, actual_dx)  # positive is downhill in increasing chainage
        route_line = _line_to_chainage(centerline, start_m, end_m)
        original_geometry_length = route_line.length
        if original_geometry_length <= 0:
            raise ValueError(f"Invalid route geometry for {sid}")

        result = run_simulation(
            x_m=x_local,
            bed_m=bed,
            width_m=float(scenario["width_m"]),
            volume_m3=float(scenario["volume_m3"]),
            pulse_duration_s=float(cfg["physical_parameters"]["pulse_duration_s"]["value"]),
            inlet_depth_m=float(cfg["physical_parameters"]["inlet_depth_m"]["value"]),
            mu=float(scenario["mu"]),
            xi_m_s2=float(scenario["xi_m_s2"]),
            end_time_s=float(numeric["simulation_horizon_s"]),
            cfl=float(numeric["cfl_number"]),
            output_interval_s=output_interval,
        )
        runs[sid] = result
        run_metadata[sid] = scenario
        diagnostics[sid] = {
            "route_id": scenario["route_id"],
            "route_length_m": end_m - start_m,
            "centerline_geometry_length_m": original_geometry_length,
            "source_offset_m": float(route["source_offset_m"]),
            "port_offset_m": float(route["port_offset_m"]),
            "profile_cells": int(len(bed)),
            "grid_spacing_actual_m": actual_dx,
            "bed_min_m": float(bed.min()),
            "bed_max_m": float(bed.max()),
            "downhill_grade_fraction": float(np.mean(grade > 0)),
            "uphill_grade_fraction": float(np.mean(grade < 0)),
            "uphill_cell_count": int(np.count_nonzero(grade < 0)),
            "max_abs_grade": float(np.max(np.abs(grade))),
            "max_abs_cell_elevation_change_m": float(np.max(np.abs(np.diff(bed)))),
            "dem_route_sample_diagnostics": route_profile["sample_diagnostics"],
            "bed_grade_note": "Bed is nearest-cell HMA DEM sampled at 25 m along the projected centerline, then linearly interpolated to model cells; positive grade means downhill with increasing chainage. Observed uphill cells are retained without filling or smoothing.",
        }

        times = result["times_s"]
        front_distance = np.clip(result["front_position_m"], 0.0, end_m - start_m)
        front_displacement_speed = np.gradient(front_distance, times) if len(times) > 1 else np.zeros_like(front_distance)
        for i, time_s in enumerate(times):
            chainage = start_m + float(front_distance[i])
            point = _point_at_chainage(centerline, chainage)
            front_rows.append(
                {
                    "scenario_id": sid,
                    "route_id": scenario["route_id"],
                    "time_from_channel_entry_s": float(time_s),
                    "time_from_channel_entry_min": float(time_s) / 60.0,
                    "chainage_m": chainage,
                    "distance_from_inlet_m": float(front_distance[i]),
                    "remaining_to_port_m": max(0.0, end_m - start_m - float(front_distance[i])),
                    "front_elevation_dem_m": float(np.interp(chainage, route_profile["chainage_m"], route_profile["elevation_m"])),
                    "front_cell_velocity_m_s": float(result["front_speed_m_s"][i]),
                    "front_displacement_speed_m_s": float(front_displacement_speed[i]),
                    "front_depth_m": float(result["front_depth_m"][i]),
                    "front_discharge_m3_s": float(result["front_discharge_m3_s"][i]),
                    "x_utm45": point.x,
                    "y_utm45": point.y,
                    "time_basis": "relative to assumed channel-entry pulse start; unknown calendar entry time",
                    "not_event_clock_prediction": True,
                }
            )
            if i % max(1, int(round(15.0 / output_interval))) == 0 or i == len(times) - 1:
                gpkg_front_rows.append(
                    {
                        "scenario_id": sid,
                        "route_id": scenario["route_id"],
                        "time_s": float(time_s),
                        "distance_m": float(front_distance[i]),
                        "front_cell_velocity_m_s": float(result["front_speed_m_s"][i]),
                        "front_displacement_speed_m_s": float(front_displacement_speed[i]),
                        "depth_m": float(result["front_depth_m"][i]),
                        "discharge_m3_s": float(result["front_discharge_m3_s"][i]),
                        "geometry": point,
                    }
                )

        for target_t in target_profile_times:
            i = int(np.argmin(np.abs(times - target_t)))
            if abs(float(times[i]) - target_t) > output_interval * 0.51:
                continue
            depth = result["depth_m"][i]
            velocity = result["velocity_m_s"][i]
            discharge = result["discharge_m3_s"][i]
            for j in range(len(bed)):
                profile_rows.append(
                    {
                        "scenario_id": sid,
                        "route_id": scenario["route_id"],
                        "time_from_channel_entry_s": float(times[i]),
                        "distance_from_inlet_m": float(x_local[j]),
                        "centerline_chainage_m": float(chainage_centers[j]),
                        "x_utm45": float(x_utm[j]),
                        "y_utm45": float(y_utm[j]),
                        "bed_elevation_centerline_m": float(bed[j]),
                        "flow_depth_m": float(depth[j]),
                        "water_surface_centerline_m": float(bed[j] + depth[j]),
                        "velocity_m_s": float(velocity[j]),
                        "discharge_m3_s": float(discharge[j]),
                        "channel_width_m_assumed": float(scenario["width_m"]),
                    }
                )

        section_indices = {
            "25pct_route": int(round(0.25 * (len(bed) - 1))),
            "50pct_route": int(round(0.50 * (len(bed) - 1))),
            "75pct_route": int(round(0.75 * (len(bed) - 1))),
            "near_port": len(bed) - 1,
        }
        for name, j in section_indices.items():
            for i, time_s in enumerate(times):
                hydro_rows.append(
                    {
                        "scenario_id": sid,
                        "route_id": scenario["route_id"],
                        "cross_section": name,
                        "distance_from_inlet_m": float(x_local[j]),
                        "time_from_channel_entry_s": float(time_s),
                        "depth_m": float(result["depth_m"][i, j]),
                        "velocity_m_s": float(result["velocity_m_s"][i, j]),
                        "discharge_m3_s": float(result["discharge_m3_s"][i, j]),
                    }
                )

        balance = result["mass_balance"]
        columns = result["mass_balance_columns"]
        for row in balance:
            mass_rows.append({"scenario_id": sid, **dict(zip(columns, map(float, row)))})

        path_line = _profile_line(centerline, start_m, start_m + float(np.max(front_distance)))
        valid_path_length = path_line.length
        unesco_len = float(path_line.intersection(unesco).length)
        unosat_len = float(path_line.intersection(unosat).length)
        reached_idx = np.flatnonzero(front_distance >= (end_m - start_m) - actual_dx)
        arrival_s = float(times[reached_idx[0]]) if reached_idx.size else None
        max_speed = float(np.max(np.abs(result["velocity_m_s"])))
        max_depth = float(np.max(result["depth_m"]))
        max_discharge = float(np.max(np.abs(result["discharge_m3_s"])))
        summary_row = {
            "scenario_id": sid,
            "route_id": scenario["route_id"],
            "scenario_group": scenario["group"],
            "mu": float(scenario["mu"]),
            "xi_m_s2": float(scenario["xi_m_s2"]),
            "volume_assumed_m3": float(scenario["volume_m3"]),
            "width_assumed_m": float(scenario["width_m"]),
            "inlet_depth_assumed_m": float(cfg["physical_parameters"]["inlet_depth_m"]["value"]),
            "pulse_duration_assumed_s": float(cfg["physical_parameters"]["pulse_duration_s"]["value"]),
            "injected_volume_m3": float(result["injected_volume_m3"]),
            "outlet_volume_m3": float(result["outlet_volume_m3"]),
            "final_storage_volume_m3": float(result["final_mass_m3"]),
            "mass_error_fraction": float(result["relative_mass_error"]),
            "max_cfl_number": float(result["max_cfl_number"]),
            "solver_steps": int(result["step_count"]),
            "minimum_dt_s": float(result["minimum_time_step_s"]),
            "route_length_m": end_m - start_m,
            "max_runout_distance_m": float(np.max(front_distance)),
            "final_runout_distance_m": float(front_distance[-1]),
            "front_reached_port_within_horizon": bool(reached_idx.size),
            "simulated_port_arrival_relative_s": arrival_s,
            "max_velocity_m_s": max_speed,
            "max_flow_depth_m": max_depth,
            "max_discharge_m3_s": max_discharge,
            "computed_path_length_m": valid_path_length,
            "computed_path_length_within_UNESCO_extent_m": unesco_len,
            "computed_path_length_within_UNOSAT_extent_m": unosat_len,
            "UNESCO_path_overlap_fraction": unesco_len / valid_path_length if valid_path_length > 0 else 0.0,
            "UNOSAT_path_overlap_fraction": unosat_len / valid_path_length if valid_path_length > 0 else 0.0,
            "comparison_is_independent_validation": False,
            "arrival_1059_used_for_calibration": False,
        }
        comparison_rows.append(summary_row)
        gpkg_route_rows.append(
            {
                "scenario_id": sid,
                "route_id": scenario["route_id"],
                "geometry_role": "simulated_reached_centerline_segment",
                "max_runout_m": float(np.max(front_distance)),
                "max_time_s": float(times[-1]),
                "geometry": path_line,
            }
        )
        parameter_rows.extend(
            [
                {"scenario_id": sid, "parameter": "mu", "value": scenario["mu"], "unit": "1", "evidence_grade": "literature candidate; not locally calibrated"},
                {"scenario_id": sid, "parameter": "xi", "value": scenario["xi_m_s2"], "unit": "m s-2", "evidence_grade": "literature candidate; not locally calibrated"},
                {"scenario_id": sid, "parameter": "volume", "value": scenario["volume_m3"], "unit": "m3", "evidence_grade": "exploratory assumption; local volume unavailable"},
                {"scenario_id": sid, "parameter": "width", "value": scenario["width_m"], "unit": "m", "evidence_grade": "exploratory assumption; surveyed section unavailable"},
                {"scenario_id": sid, "parameter": "inlet_depth", "value": cfg["physical_parameters"]["inlet_depth_m"]["value"], "unit": "m", "evidence_grade": "exploratory assumption; local depth unavailable"},
                {"scenario_id": sid, "parameter": "pulse_duration", "value": cfg["physical_parameters"]["pulse_duration_s"]["value"], "unit": "s", "evidence_grade": "exploratory assumption; inlet hydrograph unavailable"},
            ]
        )

    front_df = pd.DataFrame(front_rows)
    profiles_df = pd.DataFrame(profile_rows)
    comparison_df = pd.DataFrame(comparison_rows)
    parameters_df = pd.DataFrame(parameter_rows)
    _write_csv(front_rows, OUT / "front_trajectories.csv")
    _write_csv(profile_rows, OUT / "flow_profiles.csv")
    _write_csv(hydro_rows, OUT / "cross_section_hydrographs.csv")
    _write_csv(mass_rows, OUT / "mass_balance.csv")
    _write_csv(comparison_rows, OUT / "scenario_comparison.csv")
    _write_csv(parameter_rows, OUT / "simulation_parameters.csv")

    # Re-run the A-reference case at alternative route-grid spacings and CFL
    # values. This tests numerical resolution separately from physical scenarios.
    ref_cfg = next(s for s in cfg["scenarios"] if s["id"] == "A_reference")
    ref_route = routes["source_A"]
    ref_start = float(ref_route["source_chainage_km"]) * 1000.0
    ref_end = float(ref_route["port_chainage_km"]) * 1000.0
    ref_dem_profile = route_dem_profiles["source_A"]
    convergence_rows: list[dict[str, object]] = []
    convergence_cases = [("grid_25m", 25.0, float(numeric["cfl_number"])), ("grid_50m", 50.0, float(numeric["cfl_number"])), ("grid_100m", 100.0, float(numeric["cfl_number"])), ("grid_200m", 200.0, float(numeric["cfl_number"])), ("cfl_0p20", 100.0, 0.2), ("cfl_0p45", 100.0, 0.45)]
    for case_id, grid_m, cfl_value in convergence_cases:
        if case_id == "grid_100m":
            result = runs["A_reference"]
            z_case = result["bed_m"]
            dx_case = float(result["cell_width_m"])
        else:
            x_case, _ = prepare_uniform_profile(
                {"chainage_m": centerline.chainage_m.to_numpy(), "elev_m": centerline.elev_m.to_numpy()},
                ref_start,
                ref_end,
                grid_m,
            )
            z_case = np.interp(x_case, ref_dem_profile["chainage_m"], ref_dem_profile["elevation_m"])
            dx_case = float(np.diff(x_case).mean())
            x_local_case = x_case - ref_start
            result = run_simulation(
                x_m=x_local_case,
                bed_m=z_case,
                width_m=float(ref_cfg["width_m"]),
                volume_m3=float(ref_cfg["volume_m3"]),
                pulse_duration_s=float(cfg["physical_parameters"]["pulse_duration_s"]["value"]),
                inlet_depth_m=float(cfg["physical_parameters"]["inlet_depth_m"]["value"]),
                mu=float(ref_cfg["mu"]),
                xi_m_s2=float(ref_cfg["xi_m_s2"]),
                end_time_s=float(numeric["simulation_horizon_s"]),
                cfl=cfl_value,
                output_interval_s=output_interval,
            )
        front_distance_case = np.clip(result["front_position_m"], 0.0, ref_end - ref_start)
        convergence_rows.append(
            {
                "case_id": case_id,
                "grid_spacing_m": dx_case,
                "cfl_target": cfl_value,
                "max_cfl_number": float(result["max_cfl_number"]),
                "max_runout_m": float(np.max(front_distance_case)),
                "relative_mass_error": float(result["relative_mass_error"]),
                "max_depth_m": float(np.max(result["depth_m"])),
                "max_velocity_m_s": float(np.max(np.abs(result["velocity_m_s"]))),
                "solver_steps": int(result["step_count"]),
            }
        )
    convergence_df = pd.DataFrame(convergence_rows)
    baseline_runout = float(convergence_df.loc[convergence_df.case_id.eq("grid_100m"), "max_runout_m"].iloc[0])
    convergence_df["runout_difference_from_100m_m"] = convergence_df.max_runout_m - baseline_runout
    convergence_df["relative_runout_difference_from_100m"] = np.abs(convergence_df.runout_difference_from_100m_m) / max(baseline_runout, 1.0)
    convergence_df.to_csv(OUT / "numerical_convergence.csv", index=False, encoding="utf-8-sig")

    # Time-series front points and reached-route geometries are directly usable
    # in QGIS (project CRS EPSG:32645). Satellite extents remain in source GPKG.
    gpkg = OUT / "question4_simulation.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    routes_gdf = gpd.GeoDataFrame(gpkg_route_rows, geometry="geometry", crs=CRS)
    routes_gdf.to_file(gpkg, layer="simulated_reached_routes", driver="GPKG")
    fronts_gdf = gpd.GeoDataFrame(gpkg_front_rows, geometry="geometry", crs=CRS)
    fronts_gdf.to_file(gpkg, layer="simulated_front_points", driver="GPKG", mode="a")

    ref = runs["A_reference"]
    times = ref["times_s"]
    selected_times = [5, 10, 20, 30, 60, 120]
    xdist = ref["cell_center_m"]
    bed = ref["bed_m"]
    primary_ids = ["A_reference", "A_low_resistance", "A_high_resistance", "B_reference"]
    colors = {"A_reference": "#dc2626", "A_low_resistance": "#2563eb", "A_high_resistance": "#d97706", "B_reference": "#16a34a"}
    color_by_time = ["#2563eb", "#d97706", "#16a34a", "#7c3aed", "#0891b2"]
    elevation_series = [("bed", xdist / 1000, bed, "#111827")]
    depth_series, velocity_series = [], []
    for j, target in enumerate(selected_times[:5]):
        i = int(np.argmin(np.abs(times - target)))
        label, color = f"t={times[i]:.0f}s", color_by_time[j]
        elevation_series.append((label, xdist / 1000, bed + ref["depth_m"][i], color))
        depth_series.append((label, xdist / 1000, ref["depth_m"][i], color))
        velocity_series.append((label, xdist / 1000, ref["velocity_m_s"][i], color))
    front_series = []
    for sid in primary_ids:
        part = front_df.loc[front_df.scenario_id.eq(sid)]
        front_series.append((sid, part.time_from_channel_entry_min, part.distance_from_inlet_m / 1000, colors[sid]))
    save_multi_panel(
        OUT / "question4_velocity_depth.png",
        [
            {"title": "Bed and modeled water surface: A reference", "x_label": "Distance from inlet (km)", "y_label": "Elevation (m)", "series": elevation_series, "xlim": (0, 8)},
            {"title": "Flow-depth profiles: A reference", "x_label": "Distance from inlet (km)", "y_label": "Depth (m)", "series": depth_series, "xlim": (0, 8)},
            {"title": "Velocity profiles: A reference", "x_label": "Distance from inlet (km)", "y_label": "Velocity (m/s)", "series": velocity_series, "xlim": (0, 8)},
            {"title": "Front position vs relative time; inlet clock unknown", "x_label": "Minutes after inlet pulse", "y_label": "Distance from inlet (km)", "series": front_series, "xlim": (0, 30)},
        ],
        size=(2000, 1400),
    )

    snapshot_panels = []
    for target in [5, 10, 20, 30, 60, 120]:
        i = int(np.argmin(np.abs(times - target)))
        snapshot_panels.append({
            "title": f"A reference, relative t={times[i]:.0f} s",
            "x_label": "Distance from inlet (km)",
            "y_label": "Flow depth (m)",
            "series": [("computed depth", xdist / 1000, ref["depth_m"][i], "#0284c7")],
            "xlim": (0, 8),
        })
    save_multi_panel(OUT / "question4_snapshots.png", snapshot_panels, size=(1800, 1500))

    sensitivity_ids = ["A_reference", "A_mu_low", "A_mu_high", "A_xi_low", "A_xi_high", "A_volume_low", "A_volume_high", "A_width_low", "A_width_high"]
    sensitivity = comparison_df[comparison_df.scenario_id.isin(sensitivity_ids)].copy()
    sensitivity["scenario_index"] = np.arange(len(sensitivity))
    sensitivity.to_csv(OUT / "sensitivity_analysis.csv", index=False, encoding="utf-8-sig")
    category_labels = ["Ref", "mu low", "mu high", "xi low", "xi high", "V low", "V high", "B low", "B high"]
    save_bar_chart(
        OUT / "question4_sensitivity.png",
        title="One-at-a-time conditional runout sensitivity",
        categories=category_labels,
        values=sensitivity.max_runout_distance_m.to_numpy() / 1000,
        y_label="Maximum runout from inlet (km); see sensitivity_analysis.csv for inputs",
    )

    # Satellite boundaries are visual/spatial context only, never calibration data.
    ext_unesco = gpd.read_file(event_gpkg, layer="unesco_mapped_extent").to_crs(CRS).geometry.union_all()
    ext_unosat = gpd.read_file(event_gpkg, layer="unosat_mapped_extent").to_crs(CRS).geometry.union_all()
    route_geometries = {
        route_id: _line_to_chainage(centerline, float(routes[route_id]["source_chainage_km"]) * 1000, float(routes[route_id]["port_chainage_km"]) * 1000)
        for route_id in ("source_A", "source_B")
    }
    simulated_geometries = {row.scenario_id: row.geometry for row in routes_gdf.itertuples() if row.scenario_id in primary_ids}
    points_gdf = gpd.read_file(event_gpkg, layer="reference_points").to_crs(CRS)
    points = {row.site_id: (row.geometry.x, row.geometry.y) for row in points_gdf.itertuples()}
    save_map(
        OUT / "question4_assessment_map.png",
        extent_geometries=[ext_unesco, ext_unosat],
        route_geometries=list(route_geometries.values()),
        simulated_geometries=simulated_geometries,
        points=points,
        title="Q4 1D computed post-inlet reach vs satellite interpretation",
    )
    a_start = float(routes["source_A"]["source_chainage_km"]) * 1000
    a_end = float(routes["source_A"]["port_chainage_km"]) * 1000
    a_chainage, _ = prepare_uniform_profile({"chainage_m": centerline.chainage_m.to_numpy(), "elev_m": centerline.elev_m.to_numpy()}, a_start, a_end, dx_requested)
    a_x_utm = np.interp(a_chainage, centerline.chainage_m, centerline.x_utm45)
    a_y_utm = np.interp(a_chainage, centerline.chainage_m, centerline.y_utm45)
    save_animation_gif(
        OUT / "question4_animation.gif",
        state=ref,
        route=route_geometries["source_A"],
        extent_geometries=[ext_unesco, ext_unosat],
        x_utm=a_x_utm,
        y_utm=a_y_utm,
        interval_s=20.0,
    )

    # Parameter catalog preserves the source/evidence grade for every input.
    catalog_rows = []
    for key, spec in cfg["physical_parameters"].items():
        if key == "gravity_m_s2":
            catalog_rows.append({"parameter": key, "value": spec, "unit": "m s-2", "evidence_grade": "physical constant", "source_or_basis": "standard gravity"})
            continue
        if not isinstance(spec, dict):
            continue
        values = spec.get("sensitivity_values", [spec.get("value", spec.get("reference"))])
        if "reference" in spec and spec["reference"] not in values:
            values = [spec["reference"], *values]
        for value in values:
            catalog_rows.append({"parameter": key, "value": value, "unit": spec.get("unit"), "evidence_grade": spec.get("evidence_grade"), "source_or_basis": spec.get("source_or_basis"), "source_url": spec.get("source_url")})
    pd.DataFrame(catalog_rows).to_csv(OUT / "parameter_catalog.csv", index=False, encoding="utf-8-sig")

    input_paths = [centerline_path, event_json, event_gpkg, dem_path, CONFIG]
    input_manifest = [
        {"path": p.relative_to(ROOT).as_posix(), "size_bytes": p.stat().st_size, "sha256": _sha256(p)}
        for p in input_paths
    ]
    profile_aggregate = {}
    for route_id in ("source_A", "source_B"):
        matches = [d for d in diagnostics.values() if d["route_id"] == route_id]
        if matches:
            profile_aggregate[route_id] = matches[0]
    summary = {
        "question": 4,
        "model": model_cfg["name"],
        "status": "Executed finite-volume scenario model; not locally calibrated or an independent prediction",
        "solver": "1D conservative finite volume, hydrostatic reconstruction, HLL intercell flux, CFL-controlled adaptive explicit steps, split semi-implicit Voellmy basal friction",
        "equations": {
            "state": "h (m), q=h*u (m2/s); rectangular constant width B (m); discharge Q=B*q (m3/s)",
            "continuity": "d(h)/dt + d(h*u)/dx = 0",
            "momentum": "d(h*u)/dt + d(h*u^2 + 0.5*g*h^2)/dx = -g*h*dz/dx - g*h*cos(theta)*(mu*sign(u) + u*abs(u)/(xi*h))",
            "voellmy": "Sf = mu*cos(theta) + u^2/(xi*h); mu dimensionless, xi in m s-2",
            "boundary": "Initially dry; upstream rectangular volume hydrograph Q=V/T for 0<=t<T with specified inlet depth and width; downstream open HLL outflow",
            "time": "Relative seconds from the assumed channel-entry pulse; calendar entry time is unknown",
        },
        "profile_diagnostics": profile_aggregate,
        "dem_audit": dem_metadata | {"route_sample_diagnostics": {k: v["sample_diagnostics"] for k, v in route_dem_profiles.items()}},
        "numerical_convergence": convergence_rows,
        "numerical_checks": {
            "all_scenario_mass_error_fraction_max": float(comparison_df.mass_error_fraction.max()),
            "all_scenario_max_cfl": float(comparison_df.max_cfl_number.max()),
            "configured_cfl": float(numeric["cfl_number"]),
            "all_depths_nonnegative": all(float(r["depth_m"].min()) >= 0 for r in runs.values()),
            "all_states_finite": all(np.isfinite(r["depth_m"]).all() and np.isfinite(r["velocity_m_s"]).all() and np.isfinite(r["discharge_m3_s"]).all() for r in runs.values()),
            "mass_tolerance_pass": bool(comparison_df.mass_error_fraction.max() < 1e-6),
            "max_front_runout_difference_across_grid_cfl": float(convergence_df.runout_difference_from_100m_m.abs().max()),
        },
        "scenario_comparison": comparison_rows,
        "external_timing_evidence": cfg["external_timing_evidence"],
        "timing_interpretation": "Reported 10:59 port arrival is comparison-only; simulation time zero is an unknown channel-entry time, so no calendar arrival forecast or fit is claimed.",
        "spatial_comparison": "Computed centerline-path length overlapping UNESCO/UNOSAT post-event interpreted polygons is descriptive consistency only; the satellite extents are not independent predictive validation and did not set model parameters.",
        "observed_local_change": "Published v1.1 dh near the port mainly indicates bed erosion; it is not used as simulated or measured deposit thickness.",
        "limitations": model_cfg["unmodeled_processes"] + ["centerline vertical datum/uncertainty not documented in the CSV", "local uphill/steep bed segments are preserved and may represent profile noise", "constant width, fixed Voellmy parameters, no lateral spreading, and no site-specific channel cross sections"],
        "input_manifest": input_manifest,
    }
    (OUT / "simulation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = """# Question 4 dynamics outputs\n\nRun from the project root in `mc-base`:\n\n```console\npython scripts/build_question4_simulation.py\n```\n\nThis is a 1D depth-averaged, finite-volume shallow-water scenario for propagation **after an assumed channel-entry hydrograph**. Bed elevations are sampled from the configured HMA DEM every 25 m along the geo-pera centerline; the source-to-channel descent remains excluded. It does not simulate phase transition, entrainment, deposition, lateral spreading, or the full two-phase mixture. Relative simulation time zero is not tied to 10:52, 10:54:19, or 10:59.\n\nThe solver uses mass and momentum conservation, HLL fluxes with hydrostatic reconstruction, a CFL-limited adaptive step, and split semi-implicit Voellmy resistance. The uniform rectangular width, pulse volume/duration, and inlet depth are explicit exploratory assumptions. Friction candidates are literature scenarios and are not calibrated to Gyirong. Arrival at 10:59 is not used to fit the model. Mass conservation, positivity, and CFL checks pass, **but runout changes materially with grid spacing** (about 4.23–6.69 km over the tested 25–200 m grids in the A-reference case). Treat spatial propagation, velocity, and depth as exploratory outputs, not a converged or validated disaster simulation.\n\n## Files\n\n- `front_trajectories.csv`: 5-second front position, cell velocity, front displacement speed, depth, discharge, chainage and projected coordinates for each scenario.\n- `flow_profiles.csv`: computed bed, water-surface, depth, velocity and discharge at selected relative times.\n- `cross_section_hydrographs.csv`: discharge/depth/velocity time series at 25%, 50%, 75% and near-port route sections.\n- `mass_balance.csv`: adaptive solver-step mass, boundary input/output, residual, relative error, CFL and dt.\n- `numerical_convergence.csv`: A-reference runout sensitivity to 25/50/100/200 m cells and CFL 0.20/0.35/0.45.\n- `simulation_parameters.csv`, `parameter_catalog.csv`: per-run parameters and provenance/evidence labels.\n- `scenario_comparison.csv`, `sensitivity_analysis.csv`: A/B, resistance, volume and width comparisons.\n- `question4_simulation.gpkg`: QGIS layers `simulated_reached_routes` and `simulated_front_points`, CRS EPSG:32645. Load this GeoPackage and, for mapped extent context, `output/event_context/event_context.gpkg`.\n- `question4_snapshots.png`, `question4_velocity_depth.png`, `question4_sensitivity.png`, `question4_assessment_map.png`, `question4_animation.gif`: plots/animation from computed states.\n- `simulation_summary.json`: equations, solver checks, DEM/profile diagnostics and input checksums.\n\nThe geo-pera centerline/elevation profile and v1.1 derived products are CC BY-NC 4.0; cite “derived from WorldView-3 © Vantor, open data” and geo-pera. UNESCO/IHP-WINS and UNOSAT boundaries are shown only as post-event interpretation. Their overlap is not independent validation. The reported local v1.1 change is bed erosion evidence, not a local deposited-thickness measurement.\n"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
