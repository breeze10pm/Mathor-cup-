"""审计官方气象 CSV、逐日气温 Excel 与压缩包清单。

运行：conda run -n mc-base --no-capture-output python scripts/audit_tabular.py
原始附件只读。按官方缺失码统计，不新增插补、不自动过滤QC。
案例时刻阶段/时区未确认，不据此创建预测标签或累计降水特征。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from project_runtime import verify_input_files


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "附件"
OUTPUT = ROOT / "output" / "data_audit" / "tabular"
CONSTRAINTS = yaml.safe_load((ROOT / "config/analysis-constraints.yml").read_text(encoding="utf-8"))
REFERENCE_LITERAL = pd.Timestamp(CONSTRAINTS["case_reference"]["literal_datetime_from_problem"])
AUDIT_DATE = pd.Timestamp("2026-10-27")
FUTURE_START = AUDIT_DATE + pd.Timedelta(days=1)
SENTINELS = [CONSTRAINTS["hourly_observations"]["official_missing_value"]]
QC_DEFINITIONS = CONSTRAINTS["hourly_observations"]["qc_definitions"]
GROUP_LABELS = {"MET": "气象梯度", "RADM": "辐射", "SOIL": "土壤", "FLUX": "湍流"}
plt.rcParams.update(
    {
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "font.size": 10,
        "savefig.dpi": 180,
        "pdf.fonttype": 42,
    }
)


def dump_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def write_csv(name: str, data: object) -> None:
    pd.DataFrame(data).to_csv(OUTPUT / name, index=False, encoding="utf-8-sig")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_inventory() -> tuple[dict[int, Path], list[dict]]:
    archives = {}
    inventory = []
    for path in sorted(INPUT.iterdir()):
        if path.suffix.lower() not in (".zip", ".rar"):
            continue
        number = int(path.name[1 : path.name.index("）")])
        archives[number] = path
        row = {
            "attachment": number,
            "archive": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix.lower() == ".zip":
            with ZipFile(path) as archive:
                bad_member = archive.testzip()
                if bad_member is not None:
                    raise ValueError(f"CRC check failed: {path.name}: {bad_member}")
                members = [info for info in archive.infolist() if not info.is_dir()]
                row.update(
                    {
                        "file_count": len(members),
                        "uncompressed_bytes": sum(info.file_size for info in members),
                        "integrity_check": "all ZIP members CRC verified",
                    }
                )
        else:
            row["integrity_check"] = "SHA-256 recorded; extraction/read checks in spatial audit"
        inventory.append(row)
    if set(archives) != set(range(1, 9)):
        raise ValueError("Expected all eight numbered attachments")
    return archives, inventory


def field_description(group: str, field: str) -> str:
    if field == "Timestamp":
        return "观测标签为北京时间UTC+8（官网）；小时区间起止语义未说明"
    if field.startswith("QC_"):
        return "官网QC字典：0正确/1可疑/2错误/4插补/8缺失/9未质控；本审计不自动过滤"
    base = field.split("(")[0]
    descriptions = {
        "WS": "风速",
        "WD": "风向",
        "Ta": "空气温度",
        "RH": "相对湿度",
        "Pressure": "气压",
        "Precip": "降水量，累计区间待确认",
        "soilT": "土壤温度",
        "VWC": "土壤体积含水率",
        "G": "土壤热通量",
        "Rsd": "向下短波辐射",
        "Rsu": "向上短波辐射",
        "Rld": "向下长波辐射",
        "Rlu": "向上长波辐射",
        "Ux": "风速 x 分量，坐标方向待确认",
        "Uy": "风速 y 分量，坐标方向待确认",
        "Uz": "风速 z 分量，坐标方向待确认",
        "T_SONIC": "声温",
        "PA": "气压",
        "VPD": "水汽压亏缺",
        "LE": "潜热通量",
        "H": "感热通量",
        "TAU": "动量通量",
        "USTAR": "摩擦速度",
        "TSTAR": "温度尺度",
        "TKE": "湍动能",
        "FC_mass": "质量形式的通量；物质定义以数据说明为准",
    }
    for key in sorted(descriptions, key=len, reverse=True):
        if base == key or base.startswith(key + "_"):
            return descriptions[key] + "（按字段名解释）"
    return "字段含义需结合站点说明确认"


def range_flags(field: str, values: pd.Series) -> pd.Series:
    """仅标记由字段单位可直接约束的情况；不裁剪、不替换原始数据。"""
    result = pd.Series(False, index=values.index)
    if field.startswith(("WS_", "Precip(", "USTAR(", "TKE(")):
        result = values < 0
    elif field.startswith("WD_"):
        result = (values < 0) | (values > 360)
    elif field.startswith("RH_"):
        result = (values < 0) | (values > 100)
    elif field.startswith("VWC_"):
        result = (values < 0) | (values > 1)
    elif field.startswith(("Pressure(", "PA(")):
        result = values <= 0
    return result.fillna(False)


def audit_hourly(path: Path) -> dict:
    file_rows, field_rows, quality_rows, qc_rows, month_rows, window_rows = [], [], [], [], [], []
    groups: dict[str, list[pd.DataFrame]] = {name: [] for name in GROUP_LABELS}
    dictionary_seen = set()
    schemas = {}
    with ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            if not member.lower().endswith(".csv"):
                continue
            frame = pd.read_csv(BytesIO(archive.read(member)))
            group = member.split("_")[0]
            schemas.setdefault(group, list(frame.columns))
            year = int(re.search(r"(20\d{2})\.csv$", member).group(1))
            times = pd.to_datetime(frame["Timestamp"], format="mixed", errors="coerce")
            numeric = frame.drop(columns="Timestamp").apply(pd.to_numeric, errors="coerce")
            measurement_fields = [column for column in numeric if not column.startswith("QC_")]
            measurements = numeric[measurement_fields]
            source_measurements = frame[measurement_fields]
            source_missing = source_measurements.isna()
            parse_failure = source_measurements.notna() & measurements.isna()
            candidate = measurements.isin(SENTINELS)
            available = measurements.notna() & np.isfinite(measurements) & ~candidate
            # 仅构造诊断视图；不对原始文件做任何清洗。
            diagnostic = measurements.where(available)
            diagnostic.index = pd.DatetimeIndex(times, name="Timestamp")
            groups[group].append(diagnostic)
            expected = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
            valid_times = pd.DatetimeIndex(times.dropna())
            future = times >= FUTURE_START
            latest = times[available.any(axis=1)].max()
            row = {
                "file": member,
                "group": group,
                "year": year,
                "rows": len(frame),
                "columns": len(frame.columns),
                "measurement_columns": len(measurement_fields),
                "start": str(times.min()),
                "end": str(times.max()),
                "invalid_timestamps": int(times.isna().sum()),
                "duplicate_timestamps": int(times.duplicated().sum()),
                "missing_hour_labels": len(expected.difference(valid_times)),
                "out_of_year_labels": len(valid_times.difference(expected)),
                "is_time_sorted": bool(times.is_monotonic_increasing),
                "schema_matches_first_file": list(frame.columns) == schemas[group],
                "measurement_cells": int(measurements.size),
                "native_missing_cells": int(source_missing.sum().sum()),
                "nonnumeric_token_cells": int(parse_failure.sum().sum()),
                "nonnumeric_tokens": json.dumps(
                    {
                        str(token): int(count)
                        for token, count in source_measurements.where(parse_failure)
                        .stack()
                        .value_counts()
                        .items()
                    }
                ),
                "candidate_sentinel_cells": int(candidate.sum().sum()),
                "nonfinite_cells_excluding_nan": int(
                    (~np.isfinite(measurements) & measurements.notna()).sum().sum()
                ),
                "diagnostic_available_cells": int(available.sum().sum()),
                "diagnostic_unavailable_fraction": float(1 - available.to_numpy().mean()),
                "first_diagnostic_nonmissing_timestamp": str(times[available.any(axis=1)].min()),
                "last_diagnostic_nonmissing_timestamp": str(latest),
                "post_audit_date_rows": int(future.sum()),
                "post_audit_date_available_cells": int(available.loc[future].sum().sum()),
                "timezone": "Beijing Time UTC+8; TPDC metadata confirmed",
                "hour_interval_definition": "not specified",
            }
            file_rows.append(row)
            print(
                f"AUDITED {member}: rows={len(frame)}, diagnostic unavailable={row['diagnostic_unavailable_fraction']:.2%}",
                flush=True,
            )
            lookup = {column.lower(): column for column in frame.columns}
            for column in frame.columns:
                key = (group, column)
                if key not in dictionary_seen:
                    dictionary_seen.add(key)
                    unit = re.search(r"\((.*)\)$", column)
                    level = re.search(r"_(\d+(?:\.\d+)?)m", column)
                    qc = lookup.get(("QC_" + column.split("(")[0]).lower())
                    field_rows.append(
                        {
                            "group": group,
                            "field": column,
                            "role": "time"
                            if column == "Timestamp"
                            else "QC"
                            if column.startswith("QC_")
                            else "measurement",
                            "unit_as_header": unit.group(1) if unit else "not specified",
                            "height_or_depth_m": float(level.group(1)) if level else None,
                            "qc_field": qc,
                            "description": field_description(group, column),
                        }
                    )
                if column.startswith("QC_"):
                    for code, count in frame[column].value_counts(dropna=False).items():
                        qc_rows.append(
                            {
                                "file": member,
                                "group": group,
                                "year": year,
                                "field": column,
                                "code": str(code),
                                "meaning_official": QC_DEFINITIONS.get(code, "未定义代码"),
                                "count": int(count),
                            }
                        )
                    continue
                if column == "Timestamp":
                    continue
                source = measurements[column]
                values = diagnostic[column].reset_index(drop=True)
                usable = values.dropna()
                q1, q3 = usable.quantile([0.25, 0.75]) if len(usable) else (np.nan, np.nan)
                iqr = q3 - q1
                stats = {
                    "file": member,
                    "group": group,
                    "year": year,
                    "field": column,
                    "rows": len(frame),
                    "native_missing": int(source_missing[column].sum()),
                    "nonnumeric_token_count": int(parse_failure[column].sum()),
                    "nonnumeric_tokens": json.dumps(
                        {
                            str(token): int(count)
                            for token, count in frame.loc[parse_failure[column], column]
                            .value_counts()
                            .items()
                        }
                    ),
                    "candidate_sentinel": int(candidate[column].sum()),
                    "diagnostic_nonmissing": len(usable),
                    "diagnostic_unavailable_fraction": float(1 - len(usable) / len(frame)),
                    "range_flag_count": int(range_flags(column, values).sum()),
                    "iqr_flag_count": int(
                        ((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum()
                    )
                    if len(usable)
                    else 0,
                    "distinct_nonmissing": int(usable.nunique()),
                    "min": float(usable.min()) if len(usable) else None,
                    "median": float(usable.median()) if len(usable) else None,
                    "max": float(usable.max()) if len(usable) else None,
                    "mean": float(usable.mean()) if len(usable) else None,
                    "std": float(usable.std()) if len(usable) > 1 else None,
                    "observed_candidate_values": json.dumps(
                        {
                            str(code): int((source == code).sum())
                            for code in SENTINELS
                            if (source == code).any()
                        }
                    ),
                }
                quality_rows.append(stats)
            monthly = available.set_axis(pd.DatetimeIndex(times)).resample("MS").mean().mean(axis=1)
            for month, fraction in monthly.items():
                month_rows.append(
                    {
                        "group": group,
                        "month": str(month.date()),
                        "diagnostic_available_fraction": float(fraction),
                    }
                )
            if year == REFERENCE_LITERAL.year:
                # 仅截取相同字面日期的日历窗，不声称与真实灾害时刻对齐。
                cutoff = REFERENCE_LITERAL.floor("h")
                time_available = available.set_axis(pd.DatetimeIndex(times))
                for hours in (6, 24, 72, 168, 720):
                    window = time_available.loc[
                        (time_available.index >= cutoff - pd.Timedelta(hours=hours))
                        & (time_available.index < cutoff)
                    ]
                    for column in measurement_fields:
                        qc_column = lookup.get(("QC_" + column.split("(")[0]).lower())
                        window_mask = (times >= cutoff - pd.Timedelta(hours=hours)) & (
                            times < cutoff
                        )
                        qc_values = frame.loc[window_mask, qc_column] if qc_column else None
                        window_rows.append(
                            {
                                "group": group,
                                "field": column,
                                "hours": hours,
                                "cutoff_exclusive": str(cutoff),
                                "expected_hours": hours,
                                "present_hour_labels": len(window),
                                "diagnostic_nonmissing": int(window[column].sum()),
                                "diagnostic_available_fraction": float(
                                    window[column].sum() / hours
                                ),
                                "qc_field": qc_column,
                                "qc_nonzero_count": int((qc_values != 0).sum())
                                if qc_values is not None
                                else None,
                                "qc_codes_observed": json.dumps(
                                    {
                                        str(code): int(count)
                                        for code, count in qc_values.value_counts().items()
                                    }
                                )
                                if qc_values is not None
                                else "not supplied",
                            }
                        )
    full_groups = {group: pd.concat(frames).sort_index() for group, frames in groups.items()}
    for group, frame in full_groups.items():
        if not frame.index.is_unique:
            raise ValueError(f"Combined index is not unique for {group}")
        frame.to_parquet(OUTPUT / f"{group.lower()}_diagnostic.parquet")
    pair_rows = []
    for group, frame in full_groups.items():
        keyed = {}
        for year, part in frame.groupby(frame.index.year):
            part = part.loc[~((part.index.month == 2) & (part.index.day == 29))].copy()
            part.index = part.index.strftime("%m-%d %H:%M")
            keyed[year] = part
        for year_a in keyed:
            for year_b in keyed:
                if year_a >= year_b:
                    continue
                a, b = keyed[year_a].align(keyed[year_b], join="inner")
                common = a.notna() & b.notna()
                count = int(common.sum().sum())
                same = int(((a == b) & common).sum().sum())
                pair_rows.append(
                    {
                        "group": group,
                        "year_a": int(year_a),
                        "year_b": int(year_b),
                        "alignment": "month-day-hour; Feb29 excluded",
                        "common_diagnostic_cells": count,
                        "exact_equal_cells": same,
                        "exact_equal_fraction": same / count if count else None,
                        "same_missing_pattern": bool(a.isna().equals(b.isna())),
                        "all_measurements_identical": bool(a.equals(b)),
                    }
                )
    write_csv("hourly_files.csv", file_rows)
    write_csv("field_dictionary.csv", field_rows)
    write_csv("hourly_field_quality.csv", quality_rows)
    write_csv("qc_code_counts.csv", qc_rows)
    write_csv("monthly_availability.csv", month_rows)
    write_csv("calendar_window_availability.csv", window_rows)
    write_csv("cross_year_exact_comparison.csv", pair_rows)
    return {
        "files": file_rows,
        "dictionary": field_rows,
        "quality": quality_rows,
        "groups": full_groups,
        "cross_year": pair_rows,
        "qc_codes": sorted({row["code"] for row in qc_rows}),
    }


def audit_daily_temperature(path: Path) -> dict:
    rows, pieces = [], []
    provenance = []
    with ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            if member.lower().endswith(".doc"):
                raw = archive.read(member)
                info = {"member": member, "bytes": len(raw), "signature_hex": raw[:8].hex()}
                if raw.startswith(b"PK"):
                    from xml.etree import ElementTree as ET

                    with ZipFile(BytesIO(raw)) as document:
                        xml = ET.fromstring(document.read("word/document.xml"))
                        text = "\n".join(
                            element.text or ""
                            for element in xml.iter()
                            if element.tag.endswith("}t")
                        )
                    (OUTPUT / "provided_source_note.txt").write_text(text, encoding="utf-8")
                    info["extracted_text"] = text
                provenance.append(info)
            if not member.lower().endswith(".xlsx"):
                continue
            for sheet, frame in pd.read_excel(
                BytesIO(archive.read(member)), sheet_name=None
            ).items():
                times = pd.to_datetime(frame["时间"], errors="coerce")
                year = int(re.search(r"_(20\d{2})\.xlsx$", member).group(1))
                numeric = frame.drop(columns="时间").apply(pd.to_numeric, errors="coerce")
                expected = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
                rows.append(
                    {
                        "file": member,
                        "sheet": sheet,
                        "year": year,
                        "rows": len(frame),
                        "start": str(times.min().date()),
                        "end": str(times.max().date()),
                        "invalid_dates": int(times.isna().sum()),
                        "duplicate_dates": int(times.duplicated().sum()),
                        "calendar_days": len(expected),
                        "missing_calendar_days": len(
                            expected.difference(pd.DatetimeIndex(times.dropna()))
                        ),
                        "missing_cells": int(numeric.isna().sum().sum()),
                        "full_calendar_year": bool(
                            len(expected.difference(pd.DatetimeIndex(times.dropna()))) == 0
                        ),
                        "county_columns": ";".join(numeric.columns),
                        "unit": "degree Celsius; TPDC attachment 2 instructions confirmed",
                    }
                )
                numeric.index = pd.DatetimeIndex(times, name="date")
                pieces.append(numeric)
    combined = pd.concat(pieces).sort_index()
    if not combined.index.is_unique:
        raise ValueError("Daily temperature dates overlap")
    combined.to_parquet(OUTPUT / "daily_temperature_as_provided.parquet")
    annual = combined.groupby(combined.index.year).mean()
    annual["observed_days"] = combined.groupby(combined.index.year).size()
    annual["full_calendar_year"] = [
        pd.Timestamp(f"{year}-12-31").day_of_year == days
        for year, days in annual.observed_days.items()
    ]
    annual.reset_index().to_csv(
        OUTPUT / "daily_temperature_annual_summary.csv", index=False, encoding="utf-8-sig"
    )
    write_csv("daily_temperature_files.csv", rows)
    dump_json(OUTPUT / "source_notes.json", provenance)
    return {"files": rows, "combined": combined, "annual": annual, "provenance": provenance}


def save_figure(figure: plt.Figure, name: str) -> None:
    for suffix in ("png", "svg"):
        figure.savefig(OUTPUT / f"{name}.{suffix}", bbox_inches="tight")
    plt.close(figure)


def make_figures(hourly: dict, daily: dict) -> None:
    files = pd.DataFrame(hourly["files"])
    order = list(GROUP_LABELS)
    table = (
        files.pivot(index="group", columns="year", values="diagnostic_unavailable_fraction").loc[
            order
        ]
        * 100
    )
    figure, ax = plt.subplots(figsize=(9, 4.1), layout="constrained")
    image = ax.imshow(
        table, cmap="YlOrRd", vmin=0, vmax=max(50, table.to_numpy().max()), aspect="auto"
    )
    ax.set_xticks(range(len(table.columns)), table.columns)
    ax.set_yticks(range(len(order)), [f"{name} {GROUP_LABELS[name]}" for name in order])
    ax.set_title("小时观测缺测与非数值标记占比（未按QC进一步筛选）")
    ax.set_xlabel("年份")
    for i in range(len(table)):
        for j in range(len(table.columns)):
            value = table.iloc[i, j]
            label = "<0.1%" if 0 < value < 0.1 else f"{value:.1f}%"
            ax.text(j, i, label, ha="center", va="center", color="black")
    figure.colorbar(image, ax=ax, label="空值、非数值标记或官方缺失码（%）")
    save_figure(figure, "hourly_missingness")

    availability = []
    for group in order:
        frame = hourly["groups"][group].loc["2026"]
        availability.append(frame.notna().resample("D").mean().mean(axis=1))
    matrix = pd.DataFrame(availability, index=order)
    dates = matrix.columns
    figure, ax = plt.subplots(figsize=(12, 3.8), layout="constrained")
    image = ax.imshow(
        matrix.to_numpy() * 100,
        origin="upper",
        aspect="auto",
        cmap="viridis",
        vmin=0,
        vmax=100,
        extent=[
            mdates.date2num(dates[0]),
            mdates.date2num(dates[-1] + pd.Timedelta(days=1)),
            3.5,
            -0.5,
        ],
    )
    ax.set_yticks(range(4), order)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m月"))
    ax.set_xticks(pd.date_range("2026-01-01", "2026-12-01", freq="MS"))
    ax.axvline(FUTURE_START, color="#ef8a17", lw=1.4, linestyle="--", label="审计日之后")
    ax.set_title("2026 年逐日诊断可用率：有时间标签不等于有有效观测")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncols=2, frameon=False)
    figure.colorbar(image, ax=ax, label="诊断非缺测测量单元格（%）")
    save_figure(figure, "availability_2026")

    plot_start = (REFERENCE_LITERAL - pd.Timedelta(days=14)).normalize()
    plot_end = (REFERENCE_LITERAL + pd.Timedelta(days=2)).ceil("D")
    met = hourly["groups"]["MET"].loc[plot_start:plot_end]
    soil = hourly["groups"]["SOIL"].loc[met.index.min() : met.index.max()]
    flux = hourly["groups"]["FLUX"].loc[met.index.min() : met.index.max()]
    figure, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True, layout="constrained")
    rain = met["Precip(mm)"]
    axes[0].plot(rain.index, rain.values, lw=1, color="#477998")
    axes[0].set_ylabel("原始Precip记录\n(mm)")
    axes[0].text(
        0.01,
        0.95,
        "逐条展示，不作累计；累计方式与小时区间待确认",
        transform=axes[0].transAxes,
        va="top",
        fontsize=9,
    )
    for ax, frame, fields, ylabel in [
        (axes[1], met, ["Ta_2m(degree C)", "Ta_20m(degree C)"], "空气温度\n(℃)"),
        (axes[2], soil, ["VWC_0.1m(m3/m3)", "VWC_0.4m(m3/m3)"], "体积含水率\n(m³/m³)"),
        (axes[3], flux, ["H(W/m2)", "LE(W/m2)"], "湍流热通量\n(W/m²)"),
    ]:
        for field in fields:
            day = frame[field].resample("D").agg(["mean", "count"])
            ax.plot(
                day.index + pd.Timedelta(hours=12),
                day["mean"].where(day["count"] >= 18),
                label=field,
                lw=1.4,
            )
        ax.set_ylabel(ylabel)
        ax.legend(loc="upper left", fontsize=8, frameon=False)
    for ax in axes:
        last_available = met.dropna(how="all").index.max()
        ax.axvspan(last_available, plot_end, color="#eeeeee", zorder=-1)
        ax.set_xlim(plot_start, plot_end)
        ax.grid(alpha=0.2)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[-1].set_xlabel("观测时间标签（北京时间UTC+8；小时统计区间未明）")
    axes[0].set_title("8月观测描述：灰区为数据截止后；未标定灾害阶段时刻")
    save_figure(figure, "event_window_diagnostics")

    full = (
        daily["annual"]
        .loc[daily["annual"].full_calendar_year]
        .drop(columns=["observed_days", "full_calendar_year"])
    )
    figure, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    full.plot(ax=ax, marker="o", markersize=3, lw=1.2)
    ax.set_title("五县完整日历年的气温均值；不完整年份不参与年度对比")
    ax.set_xlabel("年份")
    ax.set_ylabel("年均2米气温（℃，单位由官网说明确认）")
    ax.set_xticks(range(int(full.index.min()), int(full.index.max()) + 1, 2))
    ax.legend(ncols=5, fontsize=9, frameon=False)
    ax.grid(alpha=0.2)
    save_figure(figure, "annual_temperature_complete_years")


def main() -> None:
    verify_input_files()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archives, inventory = make_inventory()
    dump_json(OUTPUT / "archive_manifest.json", inventory)
    write_csv("archive_manifest.csv", inventory)
    hourly = audit_hourly(archives[1])
    daily = audit_daily_temperature(archives[2])
    make_figures(hourly, daily)
    summary = {
        "audit_date": str(AUDIT_DATE.date()),
        "generated_at_local": datetime.now().astimezone().isoformat(),
        "case_literal_datetime_untyped": str(REFERENCE_LITERAL),
        "source_archives": inventory,
        "policies": {
            "raw_inputs": "read only",
            "candidate_missing_codes": SENTINELS,
            "candidate_code_confirmation": "9999.9 confirmed by TPDC instructions; original inputs unchanged",
            "qc_semantics": QC_DEFINITIONS,
            "automatic_qc_filtering": False,
            "missing_value_imputation": "none",
            "timezone": "hourly observations UTC+8 confirmed; case time zone remains unknown",
            "calendar_window": "literal calendar crop only; not an aligned pre-trigger window",
            "diagnostic_mean_plot": "daily mean shown only with at least 18 nonmissing hours",
            "diagnostic_rain_plot": "raw individual records only; no accumulated rainfall features",
            "final_prediction_labels": "deferred",
            "final_rainfall_features": "deferred",
        },
        "hourly_files": hourly["files"],
        "qc_codes_observed": hourly["qc_codes"],
        "measurement_fields": sum(row["role"] == "measurement" for row in hourly["dictionary"]),
        "cross_year_comparisons": hourly["cross_year"],
        "daily_temperature_files": daily["files"],
        "daily_temperature_rows": len(daily["combined"]),
        "source_notes": daily["provenance"],
    }
    dump_json(OUTPUT / "summary.json", summary)
    print(f"Tabular audit complete: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
