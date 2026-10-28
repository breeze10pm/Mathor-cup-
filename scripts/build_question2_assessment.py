"""Build the reproducible, non-probabilistic Question 2 assessment package.

All source files are read-only. Outputs are written under output/question2/final.
This is a conditional screen, not a calibrated trigger probability or a 2-D flow
solver. Missing water and geotechnical variables remain unknown.
"""

from __future__ import annotations

import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from netCDF4 import Dataset
from pyogrio import write_dataframe
from pyproj import Transformer
from rasterio.mask import mask as raster_mask
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import substring, unary_union

from question2_model import (
    bed_wetness_gate,
    cascade_state,
    distance_connectivity,
    scenario_index,
    slope_membership,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output" / "question2" / "final"
INITIAL = ROOT / "output" / "question2" / "initial_layers"
EVENT_GPKG = ROOT / "output" / "event_context" / "event_context.gpkg"
EVENT_SUMMARY = ROOT / "output" / "event_context" / "event_context_summary.json"
CENTERLINE_CSV = ROOT / "data" / "supplementary" / "geo-pera-v1.1" / "centerline_v2.csv"
WRF_PATH = ROOT / "data" / "wrfout_d01_2026-08-25_00_00_00"
DEM8 = ROOT / "data" / "西藏日喀则市吉隆县泥石流灾害（20260826）DEM8m数据" / "DongLinZangBu_basin_HMA8mDEM_fillAW3D30.tif"
CRS = "EPSG:32645"
TRANSITION_START = datetime.fromisoformat("2026-08-26T10:54:19+08:00")
TRANSITION_END = datetime.fromisoformat("2026-08-26T10:55:10+08:00")
RAIN_ID_CONSTANT = 5.25
RAIN_ID_EXPONENT = -0.76


def _require_inputs() -> None:
    paths = [
        EVENT_GPKG,
        EVENT_SUMMARY,
        CENTERLINE_CSV,
        DEM8,
        INITIAL / "glacier_source_cells.gpkg",
        INITIAL / "talus_inventory_32645.gpkg",
        INITIAL / "river_network_32645.gpkg",
        INITIAL / "gfs_forecast_cells.gpkg",
        WRF_PATH,
    ]
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing Question 2 inputs: " + ", ".join(missing)
            + ". Run scripts/prepare_question2_layers.py and scripts/prepare_event_context.py first."
        )


def _haversine_km(lon: np.ndarray, lat: np.ndarray, lon0: float, lat0: float) -> np.ndarray:
    lat1, lat2 = np.radians(lat), math.radians(lat0)
    dlat = lat1 - lat2
    dlon = np.radians(lon - lon0)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _percentile_rank(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    sorted_values = np.sort(reference[np.isfinite(reference)])
    if not len(sorted_values):
        return np.full(np.shape(values), np.nan)
    arr = np.asarray(values, dtype=float)
    out = np.full(arr.shape, np.nan)
    valid = np.isfinite(arr)
    out[valid] = np.searchsorted(sorted_values, arr[valid], side="right") / len(sorted_values)
    return out


def _write_layer(path: Path, frame: gpd.GeoDataFrame, layer: str, *, first: bool = False) -> None:
    write_dataframe(frame, path, layer=layer, driver="GPKG", append=not first)


def _parse_wrf_time(value: object) -> datetime:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    return datetime.strptime(str(value).replace("_", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _wrf_dynamic_records(sites: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    records: list[dict[str, object]] = []
    with Dataset(WRF_PATH) as ds:
        times_raw = np.asarray(ds.variables["Times"][:])
        times = [
            _parse_wrf_time(b"".join(row).decode("ascii") if times_raw.ndim == 2 else row)
            for row in times_raw
        ]
        lat = np.asarray(ds.variables["XLAT"][0], dtype=float)
        lon = np.asarray(ds.variables["XLONG"][0], dtype=float)
        rainc = np.asarray(ds.variables["RAINC"][:], dtype=float) if "RAINC" in ds.variables else np.zeros((len(times), *lat.shape))
        rainnc = np.asarray(ds.variables["RAINNC"][:], dtype=float) if "RAINNC" in ds.variables else np.zeros_like(rainc)
        t2 = np.asarray(ds.variables["T2"][:], dtype=float) if "T2" in ds.variables else None
        resolution_m = float(getattr(ds, "DX", math.nan))

        target_utc = [TRANSITION_START.astimezone(timezone.utc), TRANSITION_END.astimezone(timezone.utc)]
        nearest_indices = sorted({
            int(np.argmin([abs((time - target).total_seconds()) for time in times]))
            for target in target_utc
        })
        if len(nearest_indices) == 1:
            nearest_indices = [max(0, nearest_indices[0] - 1), nearest_indices[0]]

        for site in sites:
            distances = _haversine_km(lon.ravel(), lat.ravel(), float(site["longitude"]), float(site["latitude"]))
            flat_index = int(np.nanargmin(distances))
            row, col = np.unravel_index(flat_index, lat.shape)
            site_distance = float(distances[flat_index])
            for time_index in nearest_indices:
                prev_index = time_index - 1
                accum_value = float(rainc[time_index, row, col] + rainnc[time_index, row, col])
                prev_value = float(rainc[prev_index, row, col] + rainnc[prev_index, row, col]) if prev_index >= 0 else math.nan
                increment = accum_value - prev_value if prev_index >= 0 else math.nan
                if not math.isfinite(increment) or increment < 0:
                    increment = math.nan
                temp_c = float(t2[time_index, row, col] - 273.15) if t2 is not None else math.nan
                records.append(
                    {
                        "site_id": site["site_id"],
                        "source_type": "WRF d01 model",
                        "time_utc": times[time_index].isoformat(),
                        "time_beijing": times[time_index].astimezone(timezone(TRANSITION_START.utcoffset())).isoformat(),
                        "forecast_hour_from_init": (times[time_index] - times[0]).total_seconds() / 3600,
                        "rain_hour_increment_mm": increment,
                        "rain_interval_start_utc": times[prev_index].isoformat() if prev_index >= 0 else None,
                        "rain_interval_end_utc": times[time_index].isoformat(),
                        "temperature_2m_c": temp_c,
                        "rain_window_unit": "model accumulation difference over preceding nominal 1-hour output interval; interval may not align to transition seconds",
                        "nominal_grid_spacing_km": resolution_m / 1000,
                        "distance_to_nearest_grid_km": site_distance,
                        "grid_i": int(col),
                        "grid_j": int(row),
                        "geometry": Point(float(lon[row, col]), float(lat[row, col])),
                    }
                )
    return records, {"nominal_grid_spacing_m": resolution_m, "time_step_hours": 1.0, "n_times": len(times), "first_time_utc": times[0].isoformat(), "last_time_utc": times[-1].isoformat()}


def _gfs_dynamic_records(sites: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    gfs = gpd.read_file(INITIAL / "gfs_forecast_cells.gpkg", layer="forecast_by_valid_time")
    gfs["valid_time_utc"] = pd.to_datetime(gfs["valid_time_utc"], utc=True)
    target_times = pd.to_datetime(["2026-08-26T00:00:00Z", "2026-08-26T06:00:00Z"], utc=True)
    rows: list[dict[str, object]] = []
    for site in sites:
        all_dist = _haversine_km(
            gfs.longitude.to_numpy(float), gfs.latitude.to_numpy(float),
            float(site["longitude"]), float(site["latitude"]),
        )
        gfs = gfs.assign(_site_distance_km=all_dist)
        for target in target_times:
            at_time = gfs.loc[gfs.valid_time_utc.eq(target)].sort_values("_site_distance_km").head(1)
            if at_time.empty:
                continue
            row = at_time.iloc[0]
            rows.append(
                {
                    "site_id": site["site_id"],
                    "source_type": "GFS 0.25-degree forecast",
                    "time_utc": row.valid_time_utc.isoformat(),
                    "time_beijing": row.valid_time_utc.tz_convert("Asia/Shanghai").isoformat(),
                    "forecast_hour_from_init": int(row.forecast_hour),
                    "rain_hour_increment_mm": np.nan,
                    "rain_6h_mm": float(row.total_precipitation_6h) if pd.notna(row.total_precipitation_6h) else np.nan,
                    "rain_interval_start_utc": None,
                    "rain_interval_end_utc": None,
                    "temperature_2m_c": np.nan,
                    "rain_window_unit": "provider-derived 6-hour accumulation; exact interval edge semantics not confirmed",
                    "nominal_grid_spacing_km": 26.0,
                    "distance_to_nearest_grid_km": float(row["_site_distance_km"]),
                    "grid_i": None,
                    "grid_j": None,
                    "geometry": Point(float(row.longitude), float(row.latitude)),
                }
            )
    return rows, {"nominal_grid_spacing_km": 26.0, "time_step_hours": 6.0, "n_valid_times": 13, "initialization_utc": "2026-08-25T00:00:00+00:00"}


def _rainfall_threshold(duration_h: float) -> float:
    return RAIN_ID_CONSTANT * duration_h ** RAIN_ID_EXPONENT


def main() -> None:
    _require_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    for existing in OUT.iterdir():
        if existing.is_file() and existing.suffix.lower() in {".gpkg", ".csv", ".png", ".json", ".md"}:
            existing.unlink()

    context = json.loads((ROOT / "config" / "event-context.json").read_text(encoding="utf-8"))
    event_summary = json.loads(EVENT_SUMMARY.read_text(encoding="utf-8"))
    routes = event_summary["route_candidates"]
    points = gpd.read_file(EVENT_GPKG, layer="reference_points").to_crs(CRS)
    source_points = points.loc[points.site_id.isin(["source_A", "source_B"])].copy()
    talus = gpd.read_file(INITIAL / "talus_inventory_32645.gpkg", layer="talus_inventory").to_crs(CRS)
    rivers = gpd.read_file(INITIAL / "river_network_32645.gpkg", layer="river_network").to_crs(CRS)
    glacier = gpd.read_file(INITIAL / "glacier_source_cells.gpkg", layer="glacier_cells").to_crs(CRS)
    detachment = gpd.read_file(EVENT_GPKG, layer="unosat_detachment_zone").to_crs(CRS)
    centerline = pd.read_csv(CENTERLINE_CSV).sort_values("chainage_m")
    river_union = unary_union(list(rivers.geometry))
    detachment_union = unary_union(list(detachment.geometry))
    glacier_slope = glacier.slope_deg.to_numpy(float)
    slope_thresholds = {
        "low_q50_deg": float(np.nanquantile(glacier_slope, 0.50)),
        "mid_q75_deg": float(np.nanquantile(glacier_slope, 0.75)),
        "high_q90_deg": float(np.nanquantile(glacier_slope, 0.90)),
    }

    route_frames: list[gpd.GeoDataFrame] = []
    for route in routes:
        frame = gpd.read_file(EVENT_GPKG, layer="event_routes_A_B").to_crs(CRS)
        route_frames.append(frame.loc[frame.route_id.eq(route["route_id"])].copy())
    routes_union = unary_union([frame.geometry.iloc[0] for frame in route_frames])
    # Match the widest tested talus-to-channel scale; keep the actual radius explicit.
    study_area = routes_union.buffer(5000)
    for point in source_points.geometry:
        study_area = study_area.union(point.buffer(1500))

    # The raster has a non-EPSG Albers CRS. Analyze only the study-area crop,
    # preserve raw zeros in place, and mask zeros only in the derived slope view.
    with rasterio.open(DEM8) as ds:
        dem_crs = ds.crs
        dem_bounds = tuple(float(x) for x in ds.bounds)
        dem_resolution = [float(abs(x)) for x in ds.res]
        dem_nodata = ds.nodata
        full = ds.read(1, masked=True)
        full_data = np.asarray(full.data)
        full_valid = ~np.ma.getmaskarray(full) & np.isfinite(full_data)
        zero_count = int(np.count_nonzero(full_valid & (full_data == 0)))
        valid_count = int(np.count_nonzero(full_valid))
        dem_polygon_native = box(*ds.bounds)
        dem_polygon = gpd.GeoSeries([dem_polygon_native], crs=dem_crs).to_crs(CRS).iloc[0]
        study_area = study_area.intersection(dem_polygon)
        if study_area.is_empty:
            raise ValueError("The chosen route corridor does not overlap the 8 m DEM footprint")
        study_in_dem_crs = gpd.GeoSeries([study_area], crs=CRS).to_crs(dem_crs).iloc[0]
        crop, crop_transform = raster_mask(ds, [mapping(study_in_dem_crs)], crop=True, filled=False)
        crop_ma = crop[0]
        crop_data = np.asarray(crop_ma.data, dtype=np.float32)
        crop_valid = ~np.ma.getmaskarray(crop_ma) & np.isfinite(crop_data) & (crop_data != 0)
        dem_work = np.where(crop_valid, crop_data, np.nan)
        dz_dy, dz_dx = np.gradient(dem_work, dem_resolution[1], dem_resolution[0])
        slope_crop = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype(np.float32)
        slope_crop[~crop_valid] = np.nan
        to_dem = Transformer.from_crs(CRS, dem_crs, always_xy=True)

        def sample_slope_xy(x: float, y: float) -> float:
            xx, yy = to_dem.transform(x, y)
            col_f, row_f = (~crop_transform) * (xx, yy)
            row, col = int(round(row_f)), int(round(col_f))
            if not (0 <= row < slope_crop.shape[0] and 0 <= col < slope_crop.shape[1]):
                return math.nan
            return float(slope_crop[row, col]) if np.isfinite(slope_crop[row, col]) else math.nan

        def sample_slope_3x3_median(x: float, y: float) -> float:
            xx, yy = to_dem.transform(x, y)
            col_f, row_f = (~crop_transform) * (xx, yy)
            row, col = int(round(row_f)), int(round(col_f))
            window = slope_crop[max(0, row - 1):row + 2, max(0, col - 1):col + 2]
            values = window[np.isfinite(window)]
            return float(np.median(values)) if len(values) else math.nan

        def sample_line(line: LineString, step_m: float = 100.0) -> tuple[list[float], list[Point]]:
            n = max(2, int(math.ceil(line.length / step_m)) + 1)
            sample_points = [line.interpolate(float(d)) for d in np.linspace(0, line.length, n)]
            vals = [sample_slope_xy(p.x, p.y) for p in sample_points]
            return vals, sample_points

        source_points["slope_8m_deg"] = [sample_slope_xy(p.x, p.y) for p in source_points.geometry]
        source_points["slope_8m_3x3_median_deg"] = [sample_slope_3x3_median(p.x, p.y) for p in source_points.geometry]
        # Resolution comparison uses the separate native 30 m glacier grid only
        # over its footprint; no claim of full-route 30 m coverage is made.
        glacier_30_samples = [sample_slope_xy(p.x, p.y) for p in glacier.geometry]

    glacier["slope_8m_sample_deg"] = glacier_30_samples
    glacier["slope_difference_8m_minus_30m_deg"] = glacier.slope_8m_sample_deg - glacier.slope_deg
    glacier["slope_gate_q50"] = glacier.slope_deg.ge(slope_thresholds["low_q50_deg"]).astype("int8")
    glacier["slope_gate_q75"] = glacier.slope_deg.ge(slope_thresholds["mid_q75_deg"]).astype("int8")
    glacier["slope_gate_q90"] = glacier.slope_deg.ge(slope_thresholds["high_q90_deg"]).astype("int8")
    glacier["data_role"] = "30 m glacier source grid; not event-date motion or a failure label"
    thickness_ref = glacier.ice_thick_m.to_numpy(float)
    velocity_ref = glacier.velocity_m_yr.to_numpy(float)
    glacier["ice_thickness_percentile"] = _percentile_rank(thickness_ref, thickness_ref)
    glacier["velocity_climatology_percentile"] = _percentile_rank(velocity_ref, velocity_ref)

    source_rows: list[dict[str, object]] = []
    source_gdf_rows: list[dict[str, object]] = []
    for feature in source_points.itertuples():
        dists = glacier.geometry.distance(feature.geometry).to_numpy(float)
        nearest_idx = int(np.argmin(dists))
        nearest = glacier.iloc[nearest_idx]
        cell_distance = float(dists[nearest_idx])
        within_glacier_cell = cell_distance <= 22.0
        thickness_pct = float(nearest.ice_thickness_percentile) if within_glacier_cell else math.nan
        velocity_pct = float(nearest.velocity_climatology_percentile) if within_glacier_cell else math.nan
        source_components = {
            "terrain_slope_gate": None,
            "glacier_cell_support": 1.0 if within_glacier_cell else 0.0,
            "ice_thickness_percentile": thickness_pct,
            "velocity_climatology_percentile": velocity_pct,
        }
        slope = float(feature.slope_8m_3x3_median_deg)
        for threshold_name, threshold_deg in slope_thresholds.items():
            source_components["terrain_slope_gate"] = (
                float(slope >= threshold_deg) if math.isfinite(slope) else None
            )
            idx = scenario_index(source_components)
            row = {
                "candidate": feature.site_id,
                "longitude": feature.longitude,
                "latitude": feature.latitude,
                "slope_8m_nearest_cell_deg": feature.slope_8m_deg,
                "slope_8m_3x3_median_deg": slope,
                "slope_threshold_scenario": threshold_name,
                "slope_threshold_deg": threshold_deg,
                "nearest_30m_glacier_cell_distance_m": cell_distance,
                "glacier_cell_support_22m": within_glacier_cell,
                "nearest_ice_thickness_m": float(nearest.ice_thick_m) if within_glacier_cell else math.nan,
                "ice_thickness_percentile": thickness_pct,
                "surface_velocity_climatology_m_yr": float(nearest.velocity_m_yr) if within_glacier_cell else math.nan,
                "velocity_climatology_percentile": velocity_pct,
                "slope_gate_met": bool(slope >= threshold_deg) if math.isfinite(slope) else None,
                "slope_gate_membership_0_1": slope_membership(slope, slope_thresholds["low_q50_deg"], slope_thresholds["high_q90_deg"]),
                "inside_unosat_detachment_zone_comparison_only": bool(detachment_union.covers(feature.geometry)),
                "nearest_river_distance_m": float(feature.geometry.distance(river_union)),
                "nearest_talus_distance_m": float(talus.geometry.distance(feature.geometry).min()),
                "source_condition_index_0_1_not_probability": idx,
                "score_formula": "equal mean of slope gate, glacier-cell support, local ice-thickness percentile, and 2014-2024 velocity-climatology percentile; unavailable because glacier support is absent at the candidate buffers; no partial composite score is reported",
                "physical_trigger_status": "not calibrated; source mechanical properties and event-time glacier motion unavailable",
                "water_condition": None,
                "cascade_state": "indeterminate_water_unobserved",
            }
            source_rows.append(row)
            source_gdf_rows.append({**row, "geometry": feature.geometry})

    source_comparison = pd.DataFrame(source_rows)
    source_layer = gpd.GeoDataFrame(source_gdf_rows, geometry="geometry", crs=CRS)

    # Localize the loose-material inventory to a 5 km buffer around the two
    # candidate corridors. Inventory presence is not assumed to be mobile.
    local_talus = talus.loc[talus.geometry.intersects(study_area)].copy()
    if "nearest_river_m" not in local_talus:
        local_talus["nearest_river_m"] = local_talus.geometry.distance(river_union)
    local_talus["within_100m_river"] = local_talus.nearest_river_m.le(100).astype("int8")
    local_talus["within_1km_river"] = local_talus.nearest_river_m.le(1000).astype("int8")
    local_talus["within_5km_river"] = local_talus.nearest_river_m.le(5000).astype("int8")
    local_talus["connectivity_d0_100m"] = [distance_connectivity(x, 100) for x in local_talus.nearest_river_m]
    local_talus["connectivity_d0_1km"] = [distance_connectivity(x, 1000) for x in local_talus.nearest_river_m]
    local_talus["connectivity_d0_5km"] = [distance_connectivity(x, 5000) for x in local_talus.nearest_river_m]
    local_talus["interpretation"] = "loose-material inventory geometry; not event source or confirmed mobile volume"

    # Divide each projected source-to-port route into fixed 500 m reaches.
    segment_rows: list[dict[str, object]] = []
    connectivity_scales = {"low_100m": 100.0, "mid_1km": 1000.0, "high_5km": 5000.0}
    for route, frame in zip(routes, route_frames):
        line = frame.geometry.iloc[0]
        start_chain = float(route["source_chainage_km"]) * 1000
        end_chain = float(route["port_chainage_km"]) * 1000
        n_segments = int(math.ceil(line.length / 500.0))
        for i in range(n_segments):
            d0, d1 = i * 500.0, min((i + 1) * 500.0, line.length)
            seg = substring(line, d0, d1)
            chain0, chain1 = start_chain + d0, start_chain + d1
            z0 = float(np.interp(chain0, centerline.chainage_m, centerline.elev_m))
            z1 = float(np.interp(chain1, centerline.chainage_m, centerline.elev_m))
            dem_slopes, sample_points = sample_line(seg, step_m=50)
            valid_slope = np.asarray(dem_slopes, dtype=float)
            valid_slope = valid_slope[np.isfinite(valid_slope)]
            corridor = seg.buffer(250)
            nearby = local_talus.loc[local_talus.geometry.intersects(corridor)]
            talus_area = float(nearby.geometry.intersection(corridor).area.sum()) if len(nearby) else 0.0
            d_talus_river = float(nearby.nearest_river_m.min()) if len(nearby) else math.nan
            score_connectivity = {
                key: distance_connectivity(d_talus_river, scale) if math.isfinite(d_talus_river) else math.nan
                for key, scale in connectivity_scales.items()
            }
            segment_rows.append(
                {
                    "route_id": route["route_id"],
                    "segment_no": i + 1,
                    "chainage_start_km": chain0 / 1000,
                    "chainage_end_km": chain1 / 1000,
                    "segment_length_m": float(seg.length),
                    "centerline_drop_m": z0 - z1,
                    "centerline_grade_pct": 100 * (z0 - z1) / max(float(seg.length), 1),
                    "dem8m_slope_mean_deg": float(valid_slope.mean()) if len(valid_slope) else math.nan,
                    "dem8m_slope_p90_deg": float(np.quantile(valid_slope, 0.9)) if len(valid_slope) else math.nan,
                    "dem8m_slope_sample_coverage": len(valid_slope) / max(len(dem_slopes), 1),
                    "talus_inventory_area_within_250m2": talus_area,
                    "nearest_talus_to_river_m": d_talus_river,
                    **{f"talus_connectivity_{key}": value for key, value in score_connectivity.items()},
                    "water_content_m3_m3": math.nan,
                    "water_gate": None,
                    "conversion_status": "indeterminate_water_unobserved" if len(nearby) else "indeterminate_water_and_talus_unconfirmed",
                    "geometry": seg,
                }
            )
    segments = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=CRS)

    # Dynamic model context at A/B and core. WRF is hourly; GFS is 6-hourly.
    site_records = [
        {"site_id": row.site_id, "longitude": float(row.longitude), "latitude": float(row.latitude)}
        for row in points.itertuples()
    ]
    wrf_records, wrf_meta = _wrf_dynamic_records(site_records)
    gfs_records, gfs_meta = _gfs_dynamic_records(site_records)
    dynamic_records = wrf_records + gfs_records
    dynamic = gpd.GeoDataFrame(dynamic_records, geometry="geometry", crs="EPSG:4326").to_crs(CRS)

    # Scenario sensitivity: terrain thresholds derived from local 30 m source
    # grid quantiles; no threshold is fitted to the UNOSAT mapped detachment.
    sensitivity_rows: list[dict[str, object]] = []
    for row in source_comparison.itertuples():
        sensitivity_rows.append(
            {
                "experiment": "source_location_and_slope_threshold",
                "candidate": row.candidate,
                "parameter": "slope_gate_threshold_deg",
                "scenario": row.slope_threshold_scenario,
                "parameter_value": row.slope_threshold_deg,
                "unit": "degree",
                "result": row.slope_gate_met,
                "result_unit": "binary slope gate (not probability)",
                "status": "exploratory threshold comparison; local glacier-grid quantiles are not calibrated critical angles; composite source condition remains unavailable",
            }
        )
    area_total = float(local_talus.geometry.area.sum()) if len(local_talus) else 0.0
    for scenario, scale in connectivity_scales.items():
        weighted = float((local_talus.geometry.area * local_talus[f"connectivity_d0_{'100m' if scale == 100 else '1km' if scale == 1000 else '5km'}"]).sum()) if area_total else math.nan
        sensitivity_rows.append(
            {
                "experiment": "loose_material_channel_connectivity",
                "candidate": "all_local_inventory",
                "parameter": "distance_decay_length_d0_m",
                "scenario": scenario,
                "parameter_value": scale,
                "unit": "m",
                "result": weighted / area_total if area_total else math.nan,
                "result_unit": "area-weighted proximity score",
                "status": "exploratory spatial scale; not a physical connectivity threshold; inventory is not confirmed mobile material",
            }
        )
    for scenario, theta in (("low_dry_reference", 0.05), ("mid_flume_transition", 0.22), ("high_wet_reference", 0.40)):
        sensitivity_rows.append(
            {
                "experiment": "wet_bed_transformation_threshold",
                "candidate": "event_corridor",
                "parameter": "bed_volumetric_water_content_theta",
                "scenario": scenario,
                "parameter_value": theta,
                "unit": "m3/m3",
                "result": math.nan,
                "result_unit": "not evaluated",
                "status": "local bed moisture unavailable; scenario reference only; missing water is not imputed",
            }
        )
    for duration in (1.0, 6.0):
        baseline = _rainfall_threshold(duration)
        for factor_name, factor in (("low_half_threshold", 0.5), ("mid_literature_curve", 1.0), ("high_double_threshold", 2.0)):
            sensitivity_rows.append(
                {
                    "experiment": "rainfall_ID_reference_sensitivity",
                    "candidate": "nonlocal_literature_comparator",
                    "parameter": f"Icrit_at_D_{duration:g}h",
                    "scenario": factor_name,
                    "parameter_value": baseline * factor,
                    "unit": "mm/h",
                    "result": baseline,
                    "result_unit": "mm/h baseline I-D threshold",
                    "status": "Guo et al. post-Wenchuan empirical threshold with analyst sensitivity multipliers; not transferable/calibrated for this ice-rock event",
                }
            )
    sensitivity = pd.DataFrame(sensitivity_rows)

    # Resolution and spatial-comparison reliability. The comparison with the
    # detachment zone is deliberately kept separate from model construction.
    route_reliability_rows = []
    all_route_sample_points: list[tuple[str, Point, bool]] = []
    for route in routes:
        frame = next(f for f in route_frames if f.route_id.iloc[0] == route["route_id"])
        line = frame.geometry.iloc[0]
        _, samples = sample_line(line, step_m=100)
        for p in samples:
            all_route_sample_points.append((route["route_id"], p, study_area.covers(p)))
        valid_frac = float(np.mean([math.isfinite(sample_slope_xy(p.x, p.y)) for p in samples]))
        distances_to_glacier = [float(glacier.geometry.distance(p).min()) for p in samples]
        glacier_coverage = float(np.mean(np.asarray(distances_to_glacier) <= 22.0))
        route_reliability_rows.append(
            {
                "experiment": "DEM_resolution_and_route_coverage",
                "candidate": route["route_id"],
                "source_resolution": "8 m HMA filled DEM; Albers equal-area",
                "nominal_resolution_m": float(np.mean(dem_resolution)),
                "route_length_km": float(route["centerline_distance_km"]),
                "route_slope_sample_coverage_fraction": valid_frac,
                "native_30m_glacier_grid_route_coverage_fraction": glacier_coverage,
                "source_offset_to_centerline_m": float(route["source_offset_m"]),
                "interpretation": "8 m grid is the corridor terrain base; 30 m glacier products do not cover the downstream route",
            }
        )
    slope_diff = glacier.slope_difference_8m_minus_30m_deg.to_numpy(float)
    slope_diff = slope_diff[np.isfinite(slope_diff)]
    route_reliability_rows.append(
        {
            "experiment": "DEM_resolution_overlap_comparison",
            "candidate": "glacier_grid_overlap",
            "source_resolution": "8 m HMA slope versus native 30 m glacier-product slope",
            "nominal_resolution_m": 30,
            "route_length_km": math.nan,
            "route_slope_sample_coverage_fraction": float(len(slope_diff) / max(len(glacier), 1)),
            "native_30m_glacier_grid_route_coverage_fraction": math.nan,
            "source_offset_to_centerline_m": math.nan,
            "mean_slope_difference_deg_8m_minus_30m": float(slope_diff.mean()) if len(slope_diff) else math.nan,
            "median_absolute_slope_difference_deg": float(np.median(np.abs(slope_diff))) if len(slope_diff) else math.nan,
            "n_overlap_samples": int(len(slope_diff)),
            "interpretation": "resolution plus source/product differences over glacier footprint; not a pure resolution-only experiment",
        }
    )
    detachment_overlap = glacier.geometry.map(detachment_union.covers).to_numpy(bool)
    route_reliability_rows.append(
        {
            "experiment": "UNOSAT_detachment_spatial_comparison_only",
            "candidate": "glacier_source_grid",
            "source_resolution": "UNOSAT satellite interpretation vs 30 m glacier cells",
            "nominal_resolution_m": 30,
            "route_length_km": math.nan,
            "route_slope_sample_coverage_fraction": math.nan,
            "native_30m_glacier_grid_route_coverage_fraction": float(detachment_overlap.mean()),
            "source_offset_to_centerline_m": math.nan,
            "n_source_cells_inside_detachment": int(detachment_overlap.sum()),
            "n_source_cells_total": int(len(detachment_overlap)),
            "interpretation": "overlap is an in-sample spatial consistency comparison only; UNOSAT geometry did not tune parameters and is not independent accuracy validation",
        }
    )
    spatial_reliability = pd.DataFrame(route_reliability_rows)

    time_window_s = (TRANSITION_END - TRANSITION_START).total_seconds()
    def weather_distance_summary(source_label: str) -> tuple[float, float]:
        distances = [float(row["distance_to_nearest_grid_km"]) for row in dynamic_records
                     if row["source_type"] == source_label and math.isfinite(float(row["distance_to_nearest_grid_km"]))]
        return (float(np.min(distances)), float(np.max(distances))) if distances else (math.nan, math.nan)

    wrf_distance_min, wrf_distance_max = weather_distance_summary("WRF d01 model")
    gfs_distance_min, gfs_distance_max = weather_distance_summary("GFS 0.25-degree forecast")
    temporal_rows = [
        {
            "dataset": "GFS 0.25-degree forecast",
            "nominal_time_step_seconds": 6 * 3600,
            "nominal_space_scale_km": 26.0,
            "min_site_to_nearest_grid_km": gfs_distance_min,
            "max_site_to_nearest_grid_km": gfs_distance_max,
            "reference_route_length_km": 22.156,
            "transition_window_seconds": time_window_s,
            "time_step_to_window_ratio": 6 * 3600 / time_window_s,
            "interpretation": "6-hour forecast points bracket the 51-second phase by hours; cannot resolve event-minute source rainfall",
        },
        {
            "dataset": "WRF d01",
            "nominal_time_step_seconds": 3600,
            "nominal_space_scale_km": wrf_meta["nominal_grid_spacing_m"] / 1000,
            "min_site_to_nearest_grid_km": wrf_distance_min,
            "max_site_to_nearest_grid_km": wrf_distance_max,
            "reference_route_length_km": 22.156,
            "transition_window_seconds": time_window_s,
            "time_step_to_window_ratio": 3600 / time_window_s,
            "interpretation": "hourly regional model is about 71 times coarser than the reported 51-second phase window; d01 is 9 km, not d02",
        },
        {
            "dataset": "station hourly observations",
            "nominal_time_step_seconds": 3600,
            "nominal_space_scale_km": math.nan,
            "min_site_to_nearest_grid_km": math.nan,
            "max_site_to_nearest_grid_km": math.nan,
            "reference_route_length_km": 22.156,
            "transition_window_seconds": time_window_s,
            "time_step_to_window_ratio": 3600 / time_window_s,
            "interpretation": "station is described as about 65 km from port; latitude metadata conflict unresolved, and hourly accumulation support is unknown",
        },
    ]
    temporal_reliability = pd.DataFrame(temporal_rows)

    # Compare model rainfall with a published regional I-D reference, without
    # calling this event rainfall ground truth or a local calibrated trigger.
    rain_comparisons: list[dict[str, object]] = []
    for rec in wrf_records:
        if not math.isfinite(float(rec["rain_hour_increment_mm"])):
            continue
        obs = float(rec["rain_hour_increment_mm"])
        threshold = _rainfall_threshold(1.0)
        for factor in (0.5, 1.0, 2.0):
            rain_comparisons.append(
                {
                    "site_id": rec["site_id"], "dataset": "WRF d01", "valid_time_utc": rec["time_utc"],
                    "rain_amount_mm": obs, "duration_h": 1.0, "mean_intensity_mm_h": obs,
                    "reference_Icrit_mm_h": threshold * factor, "scenario_multiplier": factor,
                    "above_reference_threshold": bool(obs >= threshold * factor),
                    "interpretation": "nonlocal rainfall ID comparator only; model field, hourly interval; this event has an ice-rock cascade mechanism",
                }
            )
    for rec in gfs_records:
        if not math.isfinite(float(rec.get("rain_6h_mm", math.nan))):
            continue
        amount = float(rec["rain_6h_mm"])
        duration = 6.0
        mean_intensity = amount / duration
        threshold = _rainfall_threshold(duration)
        for factor in (0.5, 1.0, 2.0):
            rain_comparisons.append(
                {
                    "site_id": rec["site_id"], "dataset": "GFS", "valid_time_utc": rec["time_utc"],
                    "rain_amount_mm": amount, "duration_h": duration, "mean_intensity_mm_h": mean_intensity,
                    "reference_Icrit_mm_h": threshold * factor, "scenario_multiplier": factor,
                    "above_reference_threshold": bool(mean_intensity >= threshold * factor),
                    "interpretation": "nonlocal rainfall ID comparator; six-hour window alignment unresolved; not event-specific trigger calibration",
                }
            )
    rainfall_comparison = pd.DataFrame(rain_comparisons)

    # Parameter provenance / critical criteria.
    parameter_rows = [
        {"parameter": "infinite-slope factor of safety", "symbol": "FS", "unit": "dimensionless", "formula_or_critical_criterion": "FS = c'/(gamma*z*sin(alpha)) + tan(phi')/tan(alpha) - m*gamma_w*tan(phi')/(gamma*tan(alpha)); FS<=1 is idealized limit equilibrium", "low_scenario": None, "mid_scenario": 1.0, "high_scenario": None, "status": "formula only; not evaluated because cohesion, friction, failure depth, unit weight and pore pressure for the rock-ice source are unavailable; soil infinite-slope assumptions do not represent intact rock/ice", "source": "USGS OFR 2004-1348, https://pubs.usgs.gov/of/2004/1348/ofr20041348_pamphlet_Revision.pdf"},
        {"parameter": "terrain slope sensitivity", "symbol": "alpha_c", "unit": "degree", "formula_or_critical_criterion": "slope gate I(alpha>=alpha_c); use local glacier-grid q50/q75/q90 only as sensitivity cutoffs", "low_scenario": slope_thresholds["low_q50_deg"], "mid_scenario": slope_thresholds["mid_q75_deg"], "high_scenario": slope_thresholds["high_q90_deg"], "status": "data-derived exploratory screening thresholds; not physical critical angles", "source": "30 m glacier source grid in data/attachments 4; quantiles computed from its glacier-mask slope values"},
        {"parameter": "loose-material to channel proximity scale", "symbol": "d0", "unit": "m", "formula_or_critical_criterion": "C_d=exp(-d/d0), d=minimum planimetric distance from inventory polygon to supplied river line", "low_scenario": 100, "mid_scenario": 1000, "high_scenario": 5000, "status": "exploratory scales matching existing inventory distance summaries; not a physical entrainment threshold; material activity/connectivity unknown", "source": "Existing local report bands (100 m, 1 km, 5 km); analyst-defined sensitivity only"},
        {"parameter": "bed sediment volumetric water content", "symbol": "theta_b", "unit": "m3/m3", "formula_or_critical_criterion": "water gate theta_b>=theta_crit; experimental bed entrainment increased above theta_b=0.22 in a 31-degree USGS flume", "low_scenario": 0.05, "mid_scenario": 0.22, "high_scenario": 0.40, "status": "literature scenario only; local water content is unknown and no water gate is evaluated", "source": "Reid et al. 2011, https://doi.org/10.4408/IJEGE.2011-03.B-042"},
        {"parameter": "rainfall intensity-duration reference", "symbol": "I(D)", "unit": "mm/h", "formula_or_critical_criterion": "Icrit=5.25*D^-0.76, D in h; compare 0.5x/1x/2x sensitivity curves at product durations", "low_scenario": 0.5, "mid_scenario": 1.0, "high_scenario": 2.0, "status": "Wenchuan post-earthquake reference curve from 252 rainfall-triggered events; nonlocal comparator only, not fit to this ice-rock cascade", "source": "Guo et al. 2016, https://doi.org/10.1016/j.geomorph.2015.10.009; local thresholds need event/non-event data and catchment hydrology"},
        {"parameter": "channel-bank transformation controls", "symbol": "Q/Q_capacity, H_bank, beta_bank", "unit": "dimensionless, m, degree", "formula_or_critical_criterion": "case literature describes high discharge relative to channel capacity plus erodible, high/oversteepened banks; one Mount St Helens case reported banks >20 m and >45 degrees", "low_scenario": None, "mid_scenario": None, "high_scenario": None, "status": "mechanism source only; not transferred to this valley because discharge, bank geometry and erodibility are unmeasured", "source": "USGS OFR 96-0179, https://pubs.usgs.gov/of/1996/0179/report.pdf"},
        {"parameter": "downstream channel gate", "symbol": "G_route", "unit": "boolean plus grade %", "formula_or_critical_criterion": "candidate route must be connected along mapped centerline and have net positive elevation drop toward port", "low_scenario": None, "mid_scenario": None, "high_scenario": None, "status": "spatial consistency only; no minimum local slope or calibrated runout criterion is available", "source": "Public geo-pera centerline_v2.csv; local route projection in output/event_context/event_context_summary.json"},
    ]
    parameters = pd.DataFrame(parameter_rows)

    # Reliability comparisons are descriptive. The mapped detachment is never
    # used in the source score or threshold selection.
    spatial_reliability.loc[len(spatial_reliability)] = {
        "experiment": "8m_DEM_zero_anomaly",
        "candidate": "full_8m_raster",
        "source_resolution": "NCDC/HMA 8 m Albers DEM",
        "nominal_resolution_m": float(np.mean(dem_resolution)),
        "route_length_km": math.nan,
        "route_slope_sample_coverage_fraction": valid_count / max(full_valid.size, 1),
        "native_30m_glacier_grid_route_coverage_fraction": math.nan,
        "source_offset_to_centerline_m": math.nan,
        "zero_pixel_count": zero_count,
        "valid_pixel_count": valid_count,
        "zero_fraction_of_valid_pixels": zero_count / max(valid_count, 1),
        "interpretation": "zero-valued pixels are masked in the derived terrain screen and left unchanged in the source DEM pending provider clarification",
    }

    # Emit requested artifacts.
    source_comparison.to_csv(OUT / "source_scenario_comparison.csv", index=False)
    sensitivity.to_csv(OUT / "sensitivity_analysis.csv", index=False)
    spatial_reliability.to_csv(OUT / "spatial_reliability.csv", index=False)
    temporal_reliability.to_csv(OUT / "temporal_reliability.csv", index=False)
    parameters.to_csv(OUT / "trigger_parameters.csv", index=False)
    dynamic.drop(columns="geometry").to_csv(OUT / "dynamic_weather_context.csv", index=False)
    rainfall_comparison.to_csv(OUT / "rainfall_threshold_comparison.csv", index=False)

    gpkg = OUT / "condition_assessment.gpkg"
    _write_layer(gpkg, gpd.GeoDataFrame([{"study_area_type": "candidate routes buffered 5 km; clipped to 8 m DEM footprint", "source_resolution_m": float(np.mean(dem_resolution))}], geometry=[study_area], crs=CRS), "research_area", first=True)
    _write_layer(gpkg, source_layer, "source_scenarios")
    _write_layer(gpkg, segments, "route_segments_500m")
    _write_layer(gpkg, local_talus, "talus_connectivity")
    _write_layer(gpkg, glacier, "glacier_source_condition_cells")
    _write_layer(gpkg, detachment.assign(comparison_role="UNOSAT comparison only; excluded from model parameter selection"), "unosat_detachment_comparison")
    _write_layer(gpkg, dynamic, "dynamic_weather_model_context")

    # Spatial and sensitivity figures are rendered from the generated results.
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), constrained_layout=True)
    detachment.boundary.plot(ax=axes[0], color="#7c3aed", linewidth=0.9, label="UNOSAT detachment (comparison only)")
    local_talus.plot(ax=axes[0], facecolor="#d6a84f", edgecolor="#8a5a00", linewidth=0.25, alpha=0.35, label="Talus inventory")
    segments.plot(ax=axes[0], column="centerline_grade_pct", cmap="viridis", linewidth=2, legend=True)
    source_layer.drop_duplicates("candidate").plot(ax=axes[0], color=["#dc2626" if x == "source_A" else "#2563eb" for x in source_layer.drop_duplicates("candidate").candidate], markersize=45, edgecolor="white")
    axes[0].set_title("Static corridor conditions (grade colors)")
    axes[0].set_xlabel("UTM 45N easting (m)")
    axes[0].set_ylabel("UTM 45N northing (m)")
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].grid(alpha=0.2)
    axes[0].legend(fontsize=7, loc="best")

    wrf_plot = pd.DataFrame(wrf_records)
    if len(wrf_plot):
        for site in ("source_A", "source_B", "port_core"):
            part = wrf_plot.loc[wrf_plot.site_id.eq(site)].sort_values("time_utc")
            axes[1].plot(pd.to_datetime(part.time_beijing), part.rain_hour_increment_mm, marker="o", linestyle="none", label=f"WRF d01 {site}")
    axes[1].set_title("Modeled hourly rainfall increments near transition")
    axes[1].set_ylabel("RAINC + RAINNC increment (mm / nominal hour)")
    axes[1].set_xlabel("Beijing time (hourly model outputs; transition window is only 51 s)")
    axes[1].grid(alpha=0.2)
    axes[1].legend(fontsize=7)
    fig.savefig(OUT / "question2_assessment_map.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    slope_summary = []
    for name, threshold in slope_thresholds.items():
        count = int((glacier.slope_deg >= threshold).sum())
        slope_summary.append((name, threshold, count / max(len(glacier), 1)))
    axes[0].bar([x[0] for x in slope_summary], [x[2] for x in slope_summary], color=["#93c5fd", "#60a5fa", "#2563eb"])
    axes[0].set_title("Slope gate sensitivity on glacier source grid")
    axes[0].set_ylabel("Fraction of glacier cells above local quantile cutoff")
    axes[0].tick_params(axis="x", rotation=20)
    for d0, label in ((100, "100 m"), (1000, "1 km"), (5000, "5 km")):
        values = local_talus[f"connectivity_d0_{'100m' if d0 == 100 else '1km' if d0 == 1000 else '5km'}"]
        axes[1].bar(label, float((local_talus.geometry.area * values).sum() / max(area_total, 1)), color="#d6a84f")
    axes[1].set_title("Talus–river distance-scale sensitivity")
    axes[1].set_ylabel("Area-weighted proximity index (not probability)")
    fig.savefig(OUT / "question2_sensitivity.png", dpi=180)
    plt.close(fig)

    layer_rows = []
    for layer, geometry_type in gpd.list_layers(gpkg).itertuples(index=False, name=None):
        layer_frame = gpd.read_file(gpkg, layer=layer)
        layer_rows.append({"layer": layer, "feature_count": int(len(layer_frame)), "geometry_type": str(geometry_type), "crs": str(layer_frame.crs)})
    summary = {
        "question": 2,
        "model_name": "layered, evidence-aware conditional trigger screen",
        "model_status": "computed scenario indices and spatial comparisons; not a calibrated trigger probability",
        "research_area_definition": "union of the two projected source-to-port centerlines buffered 5 km, plus source buffers; clipped to the HMA 8 m DEM footprint",
        "input_files": {
            "dem8m": str(DEM8.relative_to(ROOT)),
            "glacier_source_grid": "output/question2/initial_layers/glacier_source_cells.gpkg",
            "talus_inventory": "output/question2/initial_layers/talus_inventory_32645.gpkg",
            "river_network": "output/question2/initial_layers/river_network_32645.gpkg",
            "gfs": "output/question2/initial_layers/gfs_forecast_cells.gpkg",
            "wrf": str(WRF_PATH.relative_to(ROOT)),
            "unosat_detachment": "output/event_context/event_context.gpkg:unosat_detachment_zone",
            "centerline": str(CENTERLINE_CSV.relative_to(ROOT)),
        },
        "input_checks": {
            "dem8_crs": dem_crs.to_string(), "dem8_resolution_m": dem_resolution,
            "dem8_bounds_native_crs": dem_bounds, "dem8_nodata": dem_nodata,
            "dem8_valid_pixels": valid_count, "dem8_zero_pixels": zero_count,
            "dem8_zero_fraction_valid": zero_count / max(valid_count, 1),
            "dem_zero_pixels_masked_in_derivative_only": True,
            "raw_data_modified": False,
            "glacier_crs": str(glacier.crs), "talus_crs": str(talus.crs), "river_crs": str(rivers.crs),
        },
        "source_instability": {
            "formula": "exploratory index = mean(slope gate, glacier-cell support, ice-thickness percentile, velocity-climatology percentile)",
            "components": "slope thresholds are local source-grid q50/q75/q90; ice velocity is 2014-2024 climatology, not event-time motion",
            "mechanical_factor_of_safety": "not evaluated; required site geotechnical parameters are absent",
        },
        "debris_flow_transformation": {
            "static": "talus-to-river proximity and channel profile are reported separately",
            "dynamic_water": "unknown; no local bed-water content, meltwater discharge or event-scale runoff is present; no imputation",
            "state": "indeterminate_water_unobserved",
            "critical_water_reference": "0.22 m3/m3 only in a USGS flume experiment; not transferred as a local threshold",
        },
        "downstream_propagation": {
            "route_candidates": routes,
            "output": "500 m centerline reaches with DEM slope samples, centerline drop/grade, and nearby talus inventory",
            "limit": "river/talus lines have no validated flow direction, names or active source status",
        },
        "weather_context": {
            "gfs": gfs_meta,
            "wrf_d01": wrf_meta,
            "interpretation": "model outputs only; both spatial/time steps are too coarse to resolve the 51-second transition window; not ground observations or issue-time evidence",
        },
        "spatial_validation_boundary": "UNOSAT detachment is included as a comparison layer only and was excluded from score construction/threshold selection; overlap is not independent prediction accuracy.",
        "trigger_probability": None,
        "unmet_scientific_requirements": [
            "site rock/ice strength, discontinuity geometry, basal friction and source failure-plane geometry",
            "local water content, meltwater/runoff discharge and erodible channel-bank properties",
            "event-scale observed rainfall/temperature at source and a product publication/availability time",
            "reliable event times for the 84 spatial landslides and matched non-event windows",
            "field-validated flow boundary/depth/velocity and independent events for calibration",
        ],
        "gpkg_layers": layer_rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "question2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# 第二问可提交技术版：条件触发评估\n\n## 运行\n\n在项目根目录激活 `mc-base` 后，先运行 `python scripts/prepare_question2_layers.py` 与 `python scripts/prepare_event_context.py`，再运行 `python scripts/build_question2_assessment.py`。所有输入路径相对项目根目录。程序只读原始数据，在 `output/question2/final/` 写结果。\n\n## 模型结构和公式\n\n1. **冰岩崩源区失稳：**经典浅层无限边坡因子安全系数 `FS=c'/(gamma*z*sin(alpha))+tan(phi')/tan(alpha)-m*gamma_w*tan(phi')/(gamma*tan(alpha))`，`FS<=1` 为该理想化模型的极限平衡条件。变量依次为有效黏聚力 kPa、材料重度 kN/m³、滑面深度 m、坡角/内摩擦角 degree、饱和比例 0–1、水重度 kN/m³。源区为岩冰复合体且缺强度/结构面/基底参数，故不计算虚假的本地FS。本版按8 m DEM坡度门控、30 m冰川格网支持、冰厚与2014–2024速度气候态分层展示；A/B点缺乏格网支持，故候选点复合指数为未知，不报告部分合成分数。任何0–1指数均不是概率。\n2. **沟道内碎屑流向泥石流转化：**物源可达性用 `C_d=exp(-d/d0)` 表示，`d`为岩屑坡到提供河线的距离(m)，`d0=100/1000/5000 m`仅为尺度敏感性。床层含水门控写作 `theta_b>=theta_crit`，其中水体积含量单位 m³/m³；`0.22`只在特定31°大型水槽实验出现，不是当地临界值。吉隆本地床层含水、融水流量和河岸可蚀性未知，所以模型状态保持 `indeterminate`，没有把水源补零/补一。\n3. **下游传播：**用公开中心线投影路线按500 m分段，提供高程落差、平均坡降、8 m DEM坡度样本、DEM覆盖和附近岩屑坡库存。连通路线和正落差是传播条件描述；没有现场断面、流深/流量/流速和河床参数，不能输出概率、真实流深或冲淤厚度。\n4. **降雨情景：**参考Wenchuan震后252次降雨型泥石流的 `Icrit=5.25*D^-0.76`，I单位mm/h、D单位h；仅将其作为非本地比较曲线，在1h WRF和6h GFS时段上做0.5/1/2倍敏感性。该雨量阈值不用于解释本次冰岩崩链，不作为本地触发临界值。\n\n文献来源：USGS无限边坡公式 [OFR 2004-1348](https://pubs.usgs.gov/of/2004/1348/ofr41348_pamphlet_Revision.pdf)；床层水分实验 [Reid et al. 2011](https://doi.org/10.4408/IJEGE.2011-03.B-042)；Wenchuan区域ID曲线 [Guo et al. 2016](https://doi.org/10.1016/j.geomorph.2015.10.009)；冲洪流转化案例 [USGS OFR 96-0179](https://pubs.usgs.gov/of/1996/0179/report.pdf)。不同地点的临界值不可直接移植。\n\n## 可靠性与解释边界\n\n- 8 m DEM的原始零值只在派生坡度中标记为无效；原DEM不改。报告8 m覆盖率、30 m冰川格网覆盖与二者重叠区坡度差。30 m数据只覆盖源区，不能代表整个下游沟道。\n- GFS为0.25°/6小时，WRF d01约9 km/1小时；二者只能提供模式天气背景，无法解析51秒转化窗口。研究点至最近WRF格点约4.5–6.0 km、至GFS格点约4.6–12.5 km；格点距离不代表能解析局地地形。逐小时观测站点字段含义仍需确认。\n- A/B都保留独立路线和源点情景。UNOSAT脱离区仅作事后空间一致性比较，不参与阈值选择；不报告重叠为独立验证准确率。\n- 84个灾点只用于空间层次背景，不制造小时正负标签。参数不足时分层闸门给出“条件支持/未知”，不产生校准触发概率。\n\n## 输出\n\n`condition_assessment.gpkg`含研究区、A/B源区条件、500 m路线段、岩屑坡连通、冰川源网格、UNOSAT对照区和动态天气格点，可直接在QGIS添加。其余CSV记录参数、情景、时间/空间分辨率可靠性和阈值比较；两张PNG均从计算表和几何生成。`question2_summary.json`记录输入、CRS、NoData/零值、模型限制及图层目录。\n"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    if not gpkg.exists() or len(gpd.list_layers(gpkg)) < 7:
        raise RuntimeError("GeoPackage layers were not completely written")
    required_outputs = [
        "trigger_parameters.csv", "condition_assessment.gpkg", "source_scenario_comparison.csv",
        "sensitivity_analysis.csv", "spatial_reliability.csv", "temporal_reliability.csv",
        "question2_assessment_map.png", "question2_sensitivity.png", "question2_summary.json", "README.md",
    ]
    absent = [name for name in required_outputs if not (OUT / name).is_file() or (OUT / name).stat().st_size == 0]
    if absent:
        raise RuntimeError("Required final outputs missing or empty: " + ", ".join(absent))
    print(json.dumps({"output": str(OUT.relative_to(ROOT)), "required_files": required_outputs, "gpkg_layers": layer_rows, "source_scenarios": source_comparison[["candidate", "slope_threshold_scenario", "source_condition_index_0_1_not_probability"]].to_dict("records"), "dem8_zero_fraction": zero_count / max(valid_count, 1)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
