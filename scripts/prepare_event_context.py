"""Prepare QGIS layers and a centerline profile for the 2026 event references.

All inputs are read-only. The output GeoPackage and CSV are regenerated under
output/ and contain projected copies/measurements, not edited source data.
"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyogrio import write_dataframe
from shapely.geometry import LineString, Point
from shapely.ops import substring

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SUPPLEMENT = DATA / "supplementary" / "geo-pera-v1.1"
OUT = ROOT / "output" / "event_context"
CRS = "EPSG:32645"


def _source_files() -> tuple[Path, Path, Path, Path]:
    centerline = SUPPLEMENT / "centerline_v2.csv"
    unesco_zip = DATA / "floodextent_20260826_nepal.zip"
    unosat_zip = DATA / "_static_unosat_filesystem_4259_FL20260826NPL.gdb.zip"
    dh_path = SUPPLEMENT / "bhotekoshi_dh_rasuwagadhi-timure_2m.tif"
    for path in (centerline, unesco_zip, unosat_zip, dh_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path.relative_to(ROOT)}. See docs/new-evidence-review.md "
                "for the source and acquisition instructions."
            )
    return centerline, unesco_zip, unosat_zip, dh_path


def _append_layer(path: Path, frame: gpd.GeoDataFrame, layer: str) -> None:
    write_dataframe(frame, path, layer=layer, driver="GPKG", append=path.exists())


def _clean(frame: gpd.GeoDataFrame, crs: str = CRS) -> gpd.GeoDataFrame:
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if frame.crs is None:
        raise ValueError("Input layer has no CRS; refusing to guess one")
    return frame.to_crs(crs).reset_index(drop=True)


def main() -> None:
    centerline_path, unesco_zip, unosat_zip, dh_path = _source_files()
    OUT.mkdir(parents=True, exist_ok=True)
    gpkg = OUT / "event_context.gpkg"
    if gpkg.exists():
        gpkg.unlink()

    context = json.loads((ROOT / "config" / "event-context.json").read_text(encoding="utf-8"))
    points = [
        {
            "site_id": "source_A",
            "site_type": "candidate_source",
            "longitude": context["source_coordinates"]["candidate_A"]["longitude"],
            "latitude": context["source_coordinates"]["candidate_A"]["latitude"],
            "source_note": context["source_coordinates"]["candidate_A"]["source"],
            "evidence": "user-reported reference coordinate; not surveyed boundary",
        },
        {
            "site_id": "source_B",
            "site_type": "candidate_source",
            "longitude": context["source_coordinates"]["candidate_B"]["longitude"],
            "latitude": context["source_coordinates"]["candidate_B"]["latitude"],
            "source_note": context["source_coordinates"]["candidate_B"]["source"],
            "evidence": "user-reported reference coordinate; not surveyed boundary",
        },
        {
            "site_id": "port_core",
            "site_type": "reported_impact_core",
            "longitude": context["official_impact_core_point"]["longitude"],
            "latitude": context["official_impact_core_point"]["latitude"],
            "source_note": context["official_impact_core_point"]["source"],
            "evidence": "officially reported core-area point; not exact channel cross-section",
        },
    ]
    point_frame = gpd.GeoDataFrame(
        points,
        geometry=[Point(p["longitude"], p["latitude"]) for p in points],
        crs="EPSG:4326",
    ).to_crs(CRS)

    raw = pd.read_csv(centerline_path)
    required = {"chainage_m", "x_utm45", "y_utm45", "lon", "lat", "elev_m"}
    if required - set(raw.columns):
        raise ValueError(f"Centerline fields missing: {sorted(required - set(raw.columns))}")
    raw = raw.sort_values("chainage_m").drop_duplicates("chainage_m").reset_index(drop=True)
    xy = raw[["x_utm45", "y_utm45"]].to_numpy(dtype=float)
    full_line = LineString(xy)
    geom_dist = np.r_[0.0, np.cumsum(np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1])))]
    if not np.all(np.diff(raw["chainage_m"].to_numpy()) > 0):
        raise ValueError("Centerline chainage must increase strictly")

    nearest = {}
    for record in points:
        point = point_frame.loc[point_frame.site_id.eq(record["site_id"]), "geometry"].iloc[0]
        pos_geom = full_line.project(point)
        route_point = full_line.interpolate(pos_geom)
        chainage = float(np.interp(pos_geom, geom_dist, raw["chainage_m"].to_numpy()))
        elevation = float(np.interp(chainage, raw["chainage_m"], raw["elev_m"]))
        nearest[record["site_id"]] = {
            "chainage_m": chainage,
            "offset_to_centerline_m": point.distance(route_point),
            "centerline_elevation_m": elevation,
            "projected_point": route_point,
            "geometry_distance_m": pos_geom,
        }
    start_ids = ["source_A", "source_B"]
    route_lines = []
    route_info = []
    end = nearest["port_core"]
    for site_id in start_ids:
        start = nearest[site_id]
        route_geom = substring(full_line, start["geometry_distance_m"], end["geometry_distance_m"])
        length_m = end["chainage_m"] - start["chainage_m"]
        route_info.append(
            {
                "route_id": site_id,
                "source_chainage_km": start["chainage_m"] / 1000,
                "port_chainage_km": end["chainage_m"] / 1000,
                "centerline_distance_km": length_m / 1000,
                "source_offset_m": start["offset_to_centerline_m"],
                "port_offset_m": end["offset_to_centerline_m"],
                "centerline_source_z_m": start["centerline_elevation_m"],
                "centerline_port_z_m": end["centerline_elevation_m"],
                "centerline_drop_m": start["centerline_elevation_m"] - end["centerline_elevation_m"],
                "mean_grade_pct": 100
                * (start["centerline_elevation_m"] - end["centerline_elevation_m"])
                / length_m,
                "reported_time_interval_min": 7.0,
                "event_anchored_apparent_speed_m_s": length_m / (7 * 60),
                "interpretation": "channel-centerline segment between nearest projections; not measured flow trajectory",
            }
        )
        route_lines.append(route_geom)
    routes = gpd.GeoDataFrame(route_info, geometry=route_lines, crs=CRS)

    _append_layer(gpkg, point_frame, "reference_points")
    full_line_frame = gpd.GeoDataFrame(
        [{"source": "geo-pera centerline_v2.csv", "chainage_min_m": float(raw.chainage_m.min()),
          "chainage_max_m": float(raw.chainage_m.max()), "n_vertices": len(raw)}],
        geometry=[full_line], crs=CRS,
    )
    _append_layer(gpkg, full_line_frame, "centerline_full")
    _append_layer(gpkg, routes, "event_routes_A_B")

    unesco_member = "/vsizip/" + unesco_zip.as_posix() + "/FloodExtent_20260826_Nepal.shp"
    unesco = _clean(gpd.read_file(unesco_member))
    unesco["dataset"] = "UNESCO IHP-WINS / UNOSAT cumulative satellite-detected extent"
    unesco["event_time"] = "imagery 2026-08-26/27; preliminary interpretation"
    unesco["truth_status"] = "satellite interpretation; not field-validated ground truth"
    _append_layer(gpkg, unesco, "unesco_mapped_extent")

    gdb_member = "/vsizip/" + unosat_zip.as_posix() + "/FL20260826NPL.gdb"
    unosat = gpd.read_file(
        gdb_member,
        layer="UNOSAT_Multisensor_20260826_20260828_FloodExtent",
    )
    unosat = _clean(unosat)
    unosat["truth_status"] = "UNOSAT satellite mapping; do not interpret as deposit thickness"
    _append_layer(gpkg, unosat, "unosat_mapped_extent")
    detachment = gpd.read_file(gdb_member, layer="UNOSAT_Landsat9_20260826_DetachmentZone")
    detachment = _clean(detachment)
    detachment["truth_status"] = "mapped detachment-zone interpretation; not a surveyed source boundary"
    _append_layer(gpkg, detachment, "unosat_detachment_zone")

    extent_contains = {}
    for layer_name, frame in (
        ("unesco_mapped_extent", unesco),
        ("unosat_mapped_extent", unosat),
        ("unosat_detachment_zone", detachment),
    ):
        geom = frame.geometry.union_all()
        extent_contains[layer_name] = {
            point.site_id: bool(geom.covers(point.geometry))
            for point in point_frame.itertuples()
        }
    extent_area_km2 = {
        "unesco_mapped_extent": float(unesco.geometry.area.sum() / 1e6),
        "unosat_mapped_extent": float(unosat.geometry.area.sum() / 1e6),
        "unosat_detachment_zone": float(detachment.geometry.area.sum() / 1e6),
    }

    # Sample only the measured coverage of the externally derived v1.1 change
    # raster. Nodata remains null; no interpolation or gap filling is applied.
    dh_path = SUPPLEMENT / "bhotekoshi_dh_rasuwagadhi-timure_2m.tif"
    sigma_path = SUPPLEMENT / "bhotekoshi_dh-uncertainty_rasuwagadhi-timure_2m.tif"
    profile = raw.loc[
        raw.chainage_m.between(
            min(nearest["source_A"]["chainage_m"], nearest["source_B"]["chainage_m"]),
            end["chainage_m"],
        )
    ].copy()
    profile["x_utm45"] = raw.loc[profile.index, "x_utm45"].to_numpy()
    profile["y_utm45"] = raw.loc[profile.index, "y_utm45"].to_numpy()
    coords = list(zip(profile.x_utm45, profile.y_utm45))
    with rasterio.open(dh_path) as dh, rasterio.open(sigma_path) as sigma:
        if dh.crs != sigma.crs or dh.transform != sigma.transform:
            raise ValueError("v1.1 dh and uncertainty grids do not match")
        if str(dh.crs) != CRS:
            raise ValueError(f"Unexpected v1.1 raster CRS: {dh.crs}")
        profile["dh_m"] = [float(v[0]) if v[0] != dh.nodata else np.nan for v in dh.sample(coords)]
        profile["dh_sigma_1s_m"] = [float(v[0]) if v[0] != sigma.nodata else np.nan for v in sigma.sample(coords)]
    profile["geometry"] = [Point(x, y) for x, y in coords]
    profile_frame = gpd.GeoDataFrame(profile, geometry="geometry", crs=CRS)
    profile_frame["dh_source"] = "geo-pera v1.1 corrected, measured-only elevation change; EGM2008"
    _append_layer(gpkg, profile_frame, "centerline_profile_samples")

    summary = {
        "source": "geo-pera/bhotekoshi-2026-reconstruction v1.1 centerline_v2.csv",
        "crs": CRS,
        "centerline_vertices": len(raw),
        "centerline_chainage_km": [float(raw.chainage_m.min()) / 1000, float(raw.chainage_m.max()) / 1000],
        "route_candidates": route_info,
        "mapped_extent_contains_reference_points": extent_contains,
        "mapped_extent_geometry_area_km2": extent_area_km2,
        "v11_profile_samples": int(len(profile)),
        "v11_dh_valid_samples": int(profile.dh_m.notna().sum()),
        "v11_dh_nodata_samples": int(profile.dh_m.isna().sum()),
        "v11_height_datum": "EGM2008; do not directly difference with local ellipsoidal-height DEMs",
        "warning": "Medians are centerline samples; use the release floor-masked budget for reach summaries, not this sparse centerline profile for volume.",
    }
    (OUT / "event_context_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    profile.to_csv(OUT / "centerline_event_profile.csv", index=False)
    screening = []
    for route in route_info:
        site_id = route["route_id"]
        point = next(item for item in points if item["site_id"] == site_id)
        screening.append(
            {
                "candidate": site_id,
                "longitude": point["longitude"],
                "latitude": point["latitude"],
                "evidence": point["evidence"],
                "inside_unosat_detachment_zone": extent_contains["unosat_detachment_zone"][site_id],
                "inside_unosat_mapped_extent": extent_contains["unosat_mapped_extent"][site_id],
                "inside_unesco_mapped_extent": extent_contains["unesco_mapped_extent"][site_id],
                "lateral_distance_to_centerline_m": route["source_offset_m"],
                "nearest_centerline_chainage_km": route["source_chainage_km"],
                "projected_route_to_core_km": route["centerline_distance_km"],
                "centerline_elevation_at_projection_m": route["centerline_source_z_m"],
                "reported_source_elevation_m": context["reported_source_elevation_m"],
                "hazard_probability": None,
                "reason_no_probability": "single event; no calibrated event/non-event labels or validated source polygon",
            }
        )
    pd.DataFrame(screening).to_csv(OUT / "source_candidate_screening.csv", index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
