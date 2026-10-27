"""核验审计输出与源文件的关键计数、覆盖结论和输入完整性。

这些检查验证处理流程与记录是否一致，不把源数据告警改写为合格。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "output/data_audit/tabular"
SPATIAL = ROOT / "output/data_audit/spatial"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main() -> None:
    checks = {}
    files = pd.read_csv(TAB / "hourly_files.csv")
    dictionary = pd.read_csv(TAB / "field_dictionary.csv")
    manifest = load(TAB / "archive_manifest.json")
    summary = load(SPATIAL / "spatial_summary.json")
    spatial_checks = load(SPATIAL / "validation_checks.json")
    checks["eight_original_archives_unchanged"] = len(manifest) == 8 and all(
        file_hash(ROOT / "data/附件" / row["archive"]) == row["sha256"] for row in manifest
    )
    checks["all_zip_crc_passed"] = all(
        "CRC verified" in row["integrity_check"]
        for row in manifest
        if row["archive"].endswith(".zip")
    )
    checks["hourly_file_and_field_counts"] = (
        len(files) == 24
        and int((dictionary.role == "measurement").sum()) == 63
        and int((dictionary.role == "QC").sum()) == 37
    )
    checks["hourly_schemas_and_labels"] = bool(
        files.schema_matches_first_file.all()
        and files.is_time_sorted.all()
        and (
            files[
                [
                    "invalid_timestamps",
                    "duplicate_timestamps",
                    "missing_hour_labels",
                    "out_of_year_labels",
                ]
            ]
            == 0
        )
        .all()
        .all()
    )
    decomposed = files[
        [
            "native_missing_cells",
            "nonnumeric_token_cells",
            "candidate_sentinel_cells",
            "nonfinite_cells_excluding_nan",
            "diagnostic_available_cells",
        ]
    ].sum(axis=1)
    checks["measurement_cell_counts_reconcile"] = bool(
        (decomposed == files.measurement_cells).all()
    )
    index = None
    for group in ("met", "radm", "soil", "flux"):
        frame = pd.read_parquet(TAB / f"{group}_diagnostic.parquet")
        this_ok = (
            frame.index.is_unique and len(frame) == 52584 and frame.index.is_monotonic_increasing
        )
        if index is None:
            index = frame.index
        else:
            this_ok = this_ok and frame.index.equals(index)
        checks[f"{group}_parquet_time_alignment"] = bool(this_ok)
    latest = files.loc[files.year == 2026]
    checks["2026_cutoff_consistent"] = bool(
        (latest.last_diagnostic_nonmissing_timestamp == "2026-08-27 08:00:00").all()
        and (latest.post_audit_date_available_cells == 0).all()
    )
    window = pd.read_csv(TAB / "pre_event_availability.csv")
    window = window.loc[window.hours == 72]
    checks["pre_event_72h_numeric_coverage"] = len(window) == 63 and bool(
        (window.diagnostic_nonmissing == 72).all()
    )
    daily = pd.read_csv(TAB / "daily_temperature_files.csv")
    checks["daily_temperature_calendar_coverage"] = (
        len(daily) == 21
        and int(daily.rows.sum()) == 7519
        and bool(daily.loc[daily.year < 2025, "full_calendar_year"].all())
        and int(daily.loc[daily.year == 2025, "rows"].iloc[0]) == 214
    )
    # 独立从原始ZIP读取几何，重新计算DEM矩形相交/包含，而非重读摘要计数。
    source = next((ROOT / "data/附件").glob("（6）*.zip"))
    with ZipFile(source) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".shp"))
    historical = gpd.read_file("/vsizip/" + source.as_posix() + "/" + member)
    dem_source = next((ROOT / "data/附件").glob("（7）*.zip"))
    with rasterio.open("/vsizip/" + dem_source.as_posix() + "/DEM.tif") as dem:
        projected = historical.to_crs(dem.crs)
        boundary = box(*dem.bounds)
        intersects = int(projected.intersects(boundary).sum())
        contained = int(projected.covered_by(boundary).sum())
        dem_pixels = dem.read(1, masked=True)
        valid_count = int((~np.ma.getmaskarray(dem_pixels) & np.isfinite(dem_pixels.data)).sum())
    coverage = summary["dem_historical_coverage"]
    checks["dem_coverage_independent_recalculation"] = (
        intersects == coverage["polygon_intersects_dem"] == 23
        and contained == coverage["polygon_fully_in_dem_bounds"] == 17
    )
    checks["dem_valid_pixels_independent_recalculation"] = (
        valid_count == summary["dem"]["valid_pixels"] == 2084768
    )
    landcover = pd.read_csv(SPATIAL / "landcover_spatial_coverage.csv")
    checks["landcover_source_nodata_recorded"] = len(landcover) == 4 and bool(
        (landcover.glacier_mask_cells_valid == 0).all()
    )
    for key in (
        "landcover_grid_aligned_within_tolerance",
        "all_landcover_frequency_totals_match",
        "historical_type_total_equals_records",
        "dem_pixel_count_matches_shape",
        "raster_counts_balance",
    ):
        checks[f"spatial_{key}"] = bool(spatial_checks[key])
    figures = list(TAB.glob("*.png")) + list(SPATIAL.glob("*.png"))
    checks["expected_figures_exist"] = len(figures) == 7 and all(
        path.stat().st_size > 1000 for path in figures
    )
    checks["reports_exist"] = all(
        (ROOT / "docs" / name).is_file()
        for name in ("data-audit.md", "spatial-audit.md", "data-provenance.md")
    )
    result = {
        "passed": all(checks.values()),
        "checks": checks,
        "scope": "Execution, count conservation, source hashes, and selected independent spatial recomputations; not final scientific validity or QC approval",
        "source_data_findings_retained": {
            "qc_code_meanings_unknown": True,
            "event_time_labels_not_supplied_in_historical_inventory": True,
            "netcdf_speed_component_max_difference_m_per_year": spatial_checks[
                "netcdf_velocity_hypotenuse_max_abs_error"
            ],
        },
    }
    target = ROOT / "output/data_audit/verification.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
