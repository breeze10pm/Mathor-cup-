"""Prepare first QGIS-readable source and weather layers for Question 2.

This is an input preparation step, not a calibrated trigger/hazard model.
It preserves source resolution and timestamps and creates no deposit-thickness
estimate or probability score.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, shape
import xarray as xr

from project_runtime import PROJECT_ROOT as ROOT, sha256_file

INPUTS = ROOT / "config/supplementary-inputs.json"
EVENT_CONTEXT = ROOT / "config/event-context.json"
GLACIER_NC = next((ROOT / "data/extracted/spatial/attachment_4").rglob("*.nc"))
OUT = ROOT / "output/question2/initial_layers"
NODATA = -9999.0


def _write_gpkg(frame: gpd.GeoDataFrame, name: str, layer: str) -> None:
    path = OUT / name
    if path.exists():
        path.unlink()
    frame.to_file(path, layer=layer, driver="GPKG", index=False)


def _write_geotiff(array, x, y, path: Path, *, mask=None) -> None:
    values = np.asarray(array, dtype=np.float32).copy()
    if mask is not None:
        values[~mask] = np.nan
    valid = np.isfinite(values)
    values[~valid] = NODATA
    transform = from_origin(float(x[0]) - 15, float(y[0]) + 15, 30, 30)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:32645",
        transform=transform,
        nodata=NODATA,
        compress="deflate",
        predictor=3,
    ) as dst:
        dst.write(values, 1)


def _haversine_km(lon, lat, lon0, lat0):
    lat1, lat2 = np.radians(lat), math.radians(lat0)
    dlat = lat1 - lat2
    dlon = np.radians(lon - lon0)
    a = np.sin(dlat / 2) ** 2 + math.cos(lat2) * np.cos(lat1) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _prepare_supplementary_vectors() -> dict:
    """Create projected QGIS copies without changing the input Shapefiles."""
    data_root = ROOT / "data"
    river_dir = data_root / "西藏日喀则市吉隆县泥石流灾害区河流水系数据"
    talus_dir = data_root / "西藏日喀则市吉隆县泥石流灾害区岩屑坡数据"
    river_path = next(river_dir.glob("*.shp"))
    talus_path = next(talus_dir.glob("*.shp"))

    rivers = gpd.read_file(river_path)
    with tempfile.TemporaryDirectory(prefix="mc_talus_read_") as temporary:
        copied_dir = Path(temporary) / talus_dir.name
        shutil.copytree(talus_dir, copied_dir)
        with rasterio.Env(SHAPE_RESTORE_SHX="YES"):
            talus = gpd.read_file(copied_dir / talus_path.name)

    rivers = rivers.to_crs("EPSG:32645").reset_index(drop=True)
    talus = talus.to_crs("EPSG:32645").reset_index(drop=True)
    rivers.insert(0, "river_id", np.arange(1, len(rivers) + 1, dtype=np.int32))
    talus.insert(0, "talus_id", np.arange(1, len(talus) + 1, dtype=np.int32))
    river_union = rivers.geometry.union_all()
    talus["area_calc_m2"] = talus.geometry.area
    talus["nearest_river_m"] = talus.geometry.distance(river_union)
    talus["source_basis"] = "official_talus_inventory_not_event_deposit"
    _write_gpkg(rivers, "river_network_32645.gpkg", "river_network")
    _write_gpkg(talus, "talus_inventory_32645.gpkg", "talus_inventory")

    input_files = sorted(p for folder in (river_dir, talus_dir) for p in folder.iterdir() if p.is_file())
    return {
        "river_source": str(river_path.relative_to(ROOT)),
        "talus_source": str(talus_path.relative_to(ROOT)),
        "river_rows": len(rivers),
        "talus_rows": len(talus),
        "river_bounds_epsg32645": [float(v) for v in rivers.total_bounds],
        "talus_bounds_epsg32645": [float(v) for v in talus.total_bounds],
        "talus_nearest_river_m": {
            "min": float(talus["nearest_river_m"].min()),
            "median": float(talus["nearest_river_m"].median()),
            "max": float(talus["nearest_river_m"].max()),
            "within_100m_count": int((talus["nearest_river_m"] <= 100).sum()),
            "within_1km_count": int((talus["nearest_river_m"] <= 1000).sum()),
            "within_5km_count": int((talus["nearest_river_m"] <= 5000).sum()),
        },
        "source_sidecar_hashes": {str(p.relative_to(ROOT)): sha256_file(p) for p in input_files},
        "talus_source_missing_shx": not (talus_dir / (talus_path.stem + ".shx")).exists(),
        "output_crs": "EPSG:32645",
        "note": "Projected copies only; original shapefiles are not modified.",
    }


def main() -> None:
    manifest = json.loads(INPUTS.read_text(encoding="utf-8"))
    event_context = json.loads(EVENT_CONTEXT.read_text(encoding="utf-8"))
    weather = next(row for row in manifest["inputs"] if row["topic_number"] == 3)
    archive = ROOT / weather["archive_path"]
    if archive.stat().st_size != weather["bytes"]:
        raise ValueError("Supplementary GFS archive size differs from the recorded input")
    input_hash = sha256_file(archive)
    if input_hash != weather["sha256"]:
        raise ValueError("Supplementary GFS archive hash differs from the recorded input")
    OUT.mkdir(parents=True, exist_ok=True)
    vector_metadata = _prepare_supplementary_vectors()
    core_point = event_context["official_impact_core_point"]
    impact_core = gpd.GeoDataFrame(
        [{
            "longitude": core_point["longitude"],
            "latitude": core_point["latitude"],
            "source": core_point["source"],
            "status": core_point["source_status"],
            "limit_note": core_point["interpretation_limit"],
        }],
        geometry=[Point(core_point["longitude"], core_point["latitude"])],
        crs="EPSG:4326",
    ).to_crs("EPSG:32645")
    _write_gpkg(impact_core, "official_impact_core_point_32645.gpkg", "impact_core_point")

    with xr.open_dataset(GLACIER_NC, engine="h5netcdf") as ds:
        x = np.asarray(ds["x"].values, dtype=float)
        y = np.asarray(ds["y"].values, dtype=float)
        dem = np.asarray(ds["dem"].values, dtype=np.float32)
        slope = np.asarray(ds["slope"].values, dtype=np.float32)
        thickness = np.asarray(ds["thickness"].values, dtype=np.float32)
        velocity = np.asarray(ds["v"].values, dtype=np.float32)
        mask = np.asarray(ds["glacier_mask"].values) == 1

    # Aspect derived from the supplied 30 m DEM; it is a map filter, not a
    # source-area boundary. y coordinates descend north-to-south in this file.
    dz_dy, dz_dx = np.gradient(dem, y, x)
    down_east, down_north = -dz_dx, -dz_dy
    aspect = (np.degrees(np.arctan2(down_east, down_north)) + 360) % 360
    north_facing = (aspect >= 315) | (aspect <= 45)
    band_50 = mask & (dem >= 5150) & (dem <= 5250)
    band_100 = mask & (dem >= 5100) & (dem <= 5300)

    rows, cols = np.where(mask)
    source_cells = gpd.GeoDataFrame(
        {
            "elev_m": dem[rows, cols],
            "slope_deg": slope[rows, cols],
            "aspect_deg": aspect[rows, cols],
            "ice_thick_m": thickness[rows, cols],
            "velocity_m_yr": velocity[rows, cols],
            "north_face": north_facing[rows, cols],
            "z5200_pm50": band_50[rows, cols],
            "z5200_pm100": band_100[rows, cols],
            "north_z5200_pm50": (band_50 & north_facing)[rows, cols],
            "north_z5200_pm100": (band_100 & north_facing)[rows, cols],
            "area_m2": 900,
            "source_basis": "candidate_filter_only",
        },
        geometry=[Point(float(x[c]), float(y[r])) for r, c in zip(rows, cols)],
        crs="EPSG:32645",
    )
    _write_gpkg(source_cells, "glacier_source_cells.gpkg", "glacier_cells")
    _write_geotiff(dem, x, y, OUT / "glacier_source_dem_30m.tif")
    _write_geotiff(slope, x, y, OUT / "glacier_source_slope_30m.tif")
    _write_geotiff(thickness, x, y, OUT / "glacier_ice_thickness_30m.tif", mask=mask)
    _write_geotiff(velocity, x, y, OUT / "glacier_velocity_climatology_30m.tif", mask=mask)

    transformer = gpd.GeoSeries(
        [Point(float(x.mean()), float(y.mean()))], crs="EPSG:32645"
    ).to_crs("EPSG:4326")
    source_centroid = transformer.iloc[0]

    with ZipFile(archive) as zf:
        csv_name = next(name for name in zf.namelist() if "全裁剪网格.csv" in name)
        weather_df = pd.read_csv(zf.open(csv_name), encoding="utf-8-sig")
        geojson_name = next(name for name in zf.namelist() if name.endswith("边界.geojson"))
        county_doc = json.loads(zf.read(geojson_name))
    weather_df["distance_to_glacier_grid_centroid_km"] = _haversine_km(
        weather_df["longitude"].to_numpy(),
        weather_df["latitude"].to_numpy(),
        source_centroid.x,
        source_centroid.y,
    )
    weather_gdf = gpd.GeoDataFrame(
        weather_df,
        geometry=gpd.points_from_xy(weather_df.longitude, weather_df.latitude),
        crs="EPSG:4326",
    )
    _write_gpkg(weather_gdf, "gfs_forecast_cells.gpkg", "forecast_by_valid_time")
    boundary_features = county_doc["features"]
    boundary = gpd.GeoDataFrame(
        [feature.get("properties", {}) for feature in boundary_features],
        geometry=[shape(feature["geometry"]) for feature in boundary_features],
        crs="EPSG:4326",
    )
    _write_gpkg(boundary, "gfs_county_boundary.gpkg", "county_boundary")

    if source_cells.shape[0] != int(mask.sum()):
        raise AssertionError("Not every glacier-mask cell was exported")
    if weather_df.shape[0] != 520 or weather_df["forecast_hour"].nunique() != 13:
        raise AssertionError("Unexpected GFS forecast grid/time coverage")
    if sha256_file(archive) != input_hash:
        raise AssertionError("Source archive changed while preparing QGIS layers")

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "input_preparation_only_no_trigger_score_or_deposit_thickness",
        "supplementary_archive": weather["archive_path"],
        "supplementary_archive_sha256": input_hash,
        "supplementary_vectors": vector_metadata,
        "official_impact_core_point_epsg4326": [core_point["longitude"], core_point["latitude"]],
        "glacier_source_center_candidate_wgs84": [source_centroid.x, source_centroid.y],
        "glacier_source_grid_crs": "EPSG:32645",
        "glacier_grid_cells": int(mask.sum()),
        "glacier_cells_elevation_5200_pm50": int(band_50.sum()),
        "north_facing_glacier_cells_elevation_5200_pm50": int((band_50 & north_facing).sum()),
        "glacier_cells_elevation_5200_pm100": int(band_100.sum()),
        "north_facing_glacier_cells_elevation_5200_pm100": int((band_100 & north_facing).sum()),
        "north_aspect_sector_degrees": "315..360 or 0..45",
        "gfs_grid_dimensions": {"time": 13, "latitude": 5, "longitude": 8},
        "nearest_source_grid_cell": {
            "longitude": float(weather_df.sort_values("distance_to_glacier_grid_centroid_km").iloc[0].longitude),
            "latitude": float(weather_df.sort_values("distance_to_glacier_grid_centroid_km").iloc[0].latitude),
            "distance_km_from_glacier_grid_centroid": float(
                weather_df["distance_to_glacier_grid_centroid_km"].min()
            ),
        },
        "checks": {
            "source_grid_matches_glacier_mask": True,
            "gfs_rows_match_13_by_40_grid": True,
            "source_archive_hash_unchanged": True,
            "river_network_features": vector_metadata["river_rows"] == 11,
            "talus_inventory_features": vector_metadata["talus_rows"] == 261,
            "official_core_point_feature": len(impact_core) == 1,
        },
        "layers": [
            "glacier_source_cells.gpkg (all glacier cells with exploratory elevation/aspect filters)",
            "gfs_forecast_cells.gpkg (all 40 grid centers at 13 forecast valid times)",
            "gfs_county_boundary.gpkg (boundary bundled with the GFS product)",
            "glacier_source_dem_30m.tif",
            "glacier_source_slope_30m.tif",
            "glacier_ice_thickness_30m.tif",
            "glacier_velocity_climatology_30m.tif",
            "river_network_32645.gpkg",
            "talus_inventory_32645.gpkg",
            "official_impact_core_point_32645.gpkg",
        ],
        "limitations": [
            "Glacier-grid centroid is only a reference for nearest GFS grid-cell distance, not the reported source coordinates.",
            "The 5200 m elevation bands and north-facing sector are editable map filters, not a delineated source boundary.",
            "GFS grid is 0.25 degree and cannot resolve the reported 22 km runout corridor locally.",
            "The glacier ice-thickness raster is a static glacier product, not debris-flow deposit thickness.",
            "The river network and regional talus inventory are not validated event routes or confirmed event source polygons.",
            "No verified source/outlet coordinates or pre/post-event DEM pair is currently available.",
        ],
    }
    (OUT / "layer_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    readme = """# 第二问首批 QGIS 图层\n\n这是数据准备层，不是已校准的触发概率/危险性模型。\n\n在 QGIS 中打开 `glacier_source_cells.gpkg` 和 `gfs_forecast_cells.gpkg`；另可加载同目录的 GeoTIFF。\n源区表保留全部 7,152 个冰川像元，`z5200_pm50`、`z5200_pm100` 和 `north_z5200_pm*` 是便于检查的探索过滤字段，并非确认边界。坡度、朝向按该 30m DEM 的网格导数计算。\n天气图层保留40个0.25°格点的13个预报时次；按 `forecast_hour` 与 `valid_time_utc` 过滤。GFS有效时刻使用UTC，同时保留原CSV中的北京时间列。\n\n`glacier_ice_thickness_30m.tif` 是静态冰厚，不是泥石流堆积厚度。未配准、未核实垂直基准的单张灾区DEM不能直接与它相减。\n版本与来源见 `config/supplementary-inputs.json`；全部层与限制见 `layer_manifest.json`。\n"""
    readme += "\n\n`river_network_32645.gpkg` 和 `talus_inventory_32645.gpkg` 是收到的两项官方矢量数据的投影副本；岩屑坡原 Shapefile 缺少 SHX 索引，程序仅在临时副本中重建索引。`nearest_river_m` 是库存岩屑坡到所给河网的几何距离，不证明该岩屑坡参与了本次灾害。\n\n`official_impact_core_point_32645.gpkg` 是TPDC公布的灾害核心区参考坐标。它不代表冰崩源点、泥石流触发点或精确口岸断面。\n"
    (OUT / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
