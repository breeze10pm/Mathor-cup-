"""Export a small, reproducible WRF/event-window supplement for Question 1.

Reads the official hourly station archive and the locally supplied WRF d01 file.
It does not edit source data or treat model precipitation as an observation.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset


ROOT = Path(__file__).resolve().parents[1]
STATION_ZIP = ROOT / "data" / "附件" / "（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip"
WRF_FILE = ROOT / "data" / "wrfout_d01_2026-08-25_00_00_00"
OUT = ROOT / "output" / "question1"
BEIJING = timezone(timedelta(hours=8))


def export_station_window() -> dict[str, object]:
    with zipfile.ZipFile(STATION_ZIP) as archive:
        with archive.open("MET_Gyirong_2026.csv") as source:
            frame = pd.read_csv(source, parse_dates=["Timestamp"])

    start = pd.Timestamp("2026-08-23 22:00:00")
    end = pd.Timestamp("2026-08-26 10:00:00")
    window = frame.loc[frame["Timestamp"].between(start, end)].copy()
    if len(window) != 61:
        raise ValueError(f"Expected 61 hourly labels, got {len(window)}")

    precip = pd.to_numeric(window["Precip(mm)"], errors="coerce")
    precip = precip.where(np.isfinite(precip) & precip.ne(9999.9))
    temperature = pd.to_numeric(window["Ta_2m(degree C)"], errors="coerce")
    temperature = temperature.where(np.isfinite(temperature) & temperature.ne(9999.9))
    pressure = pd.to_numeric(window["Pressure(hPa)"], errors="coerce")
    pressure = pressure.where(np.isfinite(pressure) & pressure.ne(9999.9))

    result = {
        "window_basis": "61 inclusive hourly labels; Beijing time; 2026-08-23 22:00 through 2026-08-26 10:00",
        "timestamp_support": "hourly interval meaning remains unconfirmed",
        "precipitation_qc_column": False,
        "precip_valid_labels": int(precip.notna().sum()),
        "precip_missing_or_sentinel_labels": int(precip.isna().sum()),
        "precip_labels_gt_0_1_mm": int(precip.gt(0.1).sum()),
        "precip_positive_labels": int(precip.gt(0).sum()),
        "precip_observed_values_all_zero": bool(precip.notna().all() and precip.eq(0).all()),
        "ta_2m_qc0_labels": int(window["QC_Ta_2m"].eq(0).sum()),
        "ta_2m_min_c": float(temperature.min()),
        "ta_2m_max_c": float(temperature.max()),
        "pressure_qc0_labels": int(window["QC_Pressure"].eq(0).sum()),
        "pressure_min_hpa": float(pressure.min()),
        "pressure_max_hpa": float(pressure.max()),
        "interpretation": "Station record only; no precipitation values above 0.1 mm in this label window. The record alone does not prove the trigger mechanism or instrument completeness.",
    }
    return result


def export_sentinel_arithmetic_check() -> dict[str, object]:
    with zipfile.ZipFile(STATION_ZIP) as archive:
        with archive.open("MET_Gyirong_2021.csv") as source:
            frame = pd.read_csv(source)
    values = pd.to_numeric(frame["Precip(mm)"], errors="coerce")
    masked = values.where(np.isfinite(values) & values.ne(9999.9))
    return {
        "year": 2021,
        "record_labels": int(len(values)),
        "sentinel_9999_9_count": int(values.eq(9999.9).sum()),
        "other_missing_count": int(values.isna().sum()),
        "raw_arithmetic_sum_including_sentinel_mm": float(values.sum(skipna=True)),
        "arithmetic_sum_after_sentinel_mask_mm": float(masked.sum(skipna=True)),
        "valid_numeric_labels_after_mask": int(masked.notna().sum()),
        "interpretation": "Sentinel-handling arithmetic check only; not a validated annual precipitation total because hourly support and accumulation/reset semantics remain unconfirmed.",
    }


def export_wrf_core_series() -> dict[str, object]:
    core_lon, core_lat = 85.3766, 28.2785
    with Dataset(WRF_FILE, "r") as ds:
        lat = np.asarray(ds.variables["XLAT"][0], dtype=float)
        lon = np.asarray(ds.variables["XLONG"][0], dtype=float)
        dist2 = ((lat - core_lat) * 111.2) ** 2 + (
            (lon - core_lon) * 111.2 * np.cos(np.deg2rad(core_lat))
        ) ** 2
        row, col = np.unravel_index(np.nanargmin(dist2), dist2.shape)
        distance_km = float(np.sqrt(dist2[row, col]))

        times = [
            datetime.strptime(b"".join(item).decode("ascii"), "%Y-%m-%d_%H:%M:%S")
            .replace(tzinfo=timezone.utc)
            for item in ds.variables["Times"][:]
        ]

        def series(name: str) -> np.ndarray:
            return np.asarray(ds.variables[name][:, row, col], dtype=float)

        rainc = series("RAINC")
        rainnc = series("RAINNC")
        rainsh = series("RAINSH")
        # RAINC is documented as total cumulus precipitation. Keep RAINSH
        # separate as a shallow-cumulus diagnostic to avoid double counting.
        rain_total = rainc + rainnc
        rain_increment = np.r_[np.nan, np.diff(rain_total)]

        table = pd.DataFrame(
            {
                "time_utc": [t.isoformat() for t in times],
                "time_beijing": [t.astimezone(BEIJING).isoformat() for t in times],
                "rainc_accum_mm": rainc,
                "rainnc_accum_mm": rainnc,
                "rainsh_accum_mm": rainsh,
                "rain_total_accum_mm": rain_total,
                "rain_accum_change_since_previous_output_mm": rain_increment,
                "t2_k": series("T2"),
                "u10_m_s": series("U10"),
                "v10_m_s": series("V10"),
                "pblh_m": series("PBLH"),
            }
        )
        table.to_csv(OUT / "wrf_d01_core_context.csv", index=False)

        time_local = pd.to_datetime(table["time_beijing"])
        event_near = time_local.between(
            pd.Timestamp("2026-08-26 08:00:00+08:00"),
            pd.Timestamp("2026-08-26 11:00:00+08:00"),
        )
        event_changes = table.loc[event_near, "rain_accum_change_since_previous_output_mm"]
        return {
            "file": "data/wrfout_d01_2026-08-25_00_00_00",
            "grid_id": int(ds.getncattr("GRID_ID")),
            "dx_m": float(ds.getncattr("DX")),
            "dy_m": float(ds.getncattr("DY")),
            "time_count": len(times),
            "first_time_utc": times[0].isoformat(),
            "last_time_utc": times[-1].isoformat(),
            "domain_lat_range": [float(np.nanmin(lat)), float(np.nanmax(lat))],
            "domain_lon_range": [float(np.nanmin(lon)), float(np.nanmax(lon))],
            "nearest_core_grid_row": int(row),
            "nearest_core_grid_col": int(col),
            "nearest_core_grid_lat": float(lat[row, col]),
            "nearest_core_grid_lon": float(lon[row, col]),
            "nearest_core_grid_distance_km": distance_km,
            "rain_accumulation_definition": "RAINC + RAINNC model accumulations; RAINSH is exported separately and not added because RAINC is documented as total cumulus precipitation",
            "negative_accumulation_change_count_at_nearest_core_grid": int(np.sum(np.diff(rain_total) < -1e-5)),
            "event_period_beijing": "2026-08-26 08:00–11:00; hourly model outputs",
            "event_period_accumulation_changes_mm": [float(x) for x in event_changes if np.isfinite(x)],
            "interpretation": "Modeled d01 outer-domain context, not a rain-gauge observation; nearest grid is about 6 km from the reported core point and cannot resolve the source channel.",
        }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_from": [
            STATION_ZIP.relative_to(ROOT).as_posix(),
            WRF_FILE.relative_to(ROOT).as_posix(),
        ],
        "station": export_station_window(),
        "sentinel_arithmetic_check": export_sentinel_arithmetic_check(),
        "wrf_d01": export_wrf_core_series(),
        "evidence_boundary": "The reported 10:52 ice-collapse onset and 10:59 arrival are user-reported event times. They are not reclassified here as observed model times or exact trigger time.",
    }
    (OUT / "wrf_station_event_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
