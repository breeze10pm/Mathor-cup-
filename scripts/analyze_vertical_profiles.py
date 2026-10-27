"""Simultaneous MET vertical profiles and Beijing wall-clock descriptions.

Run: conda run -n mc-base --no-capture-output python scripts/analyze_vertical_profiles.py
Source archives are read-only. No interpolation, rain features, or event labels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from itertools import product
import json
from pathlib import Path
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
import yaml

from explore_observations import record_states, sha256

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/vertical_profiles"
HEIGHTS = (1, 2, 4, 10, 20)
LAYERS = ((1, 2), (2, 4), (4, 10), (10, 20), (2, 20))
YEARS = (2022, 2023, 2024, 2025)
VIEWS = {"qc0": {0}, "qc0_plus4": {0, 4}}
MIN_LABELS = 30
VARIABLES = {
    "Ta": ("degree C", "deg C", "deg C/m"),
    "WS": ("m/s", "m/s", "(m/s)/m"),
    "RH": ("%", "%", "percentage points/m"),
}


def exact_field(variable, height):
    return f"{variable}_{height}m({VARIABLES[variable][0]})"


def validate_axes(values, quality):
    if not isinstance(values.index, pd.DatetimeIndex):
        raise ValueError("DatetimeIndex with source Beijing wall-clock labels required")
    if not values.index.equals(quality.index) or not values.columns.equals(quality.columns):
        raise ValueError("Value and QC axes must match exactly")
    if not values.index.is_unique or not values.index.is_monotonic_increasing:
        raise ValueError("Unique ordered labels required; duplicated labels cannot count twice")
    if values.index.tz is not None:
        raise ValueError("Expected naive source Beijing wall-clock labels; do not shift timezones")
    if tuple(values.columns) != HEIGHTS:
        raise ValueError("Exactly ordered 1/2/4/10/20 m heights required")


def numeric_and_qc(values, quality):
    validate_axes(values, quality)
    numeric = values.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.where(np.isfinite(numeric) & numeric.ne(9999.9))
    return numeric, quality.apply(pd.to_numeric, errors="coerce")


def eligible_profiles(values, quality, allowed_qc):
    """Each variable has one five-height mask shared by all its profile levels."""
    numeric, qc = numeric_and_qc(values, quality)
    mask = (numeric.notna() & qc.isin(allowed_qc)).all(axis=1)
    return numeric.where(mask, axis=0), mask


def paired_gradients(values, quality, allowed_qc):
    """Upper minus lower at the same label, divided by actual height spacing."""
    numeric, qc = numeric_and_qc(values, quality)
    result = {}
    for lower, upper in LAYERS:
        finite = numeric[[lower, upper]].notna().all(axis=1)
        quality_ok = qc[[lower, upper]].isin(allowed_qc).all(axis=1)
        eligible = finite & quality_ok
        difference = (numeric[upper] - numeric[lower]).where(eligible)
        result[(lower, upper)] = pd.DataFrame(
            {
                "difference": difference,
                "gradient": difference / (upper - lower),
                "eligible": eligible,
                "both_finite": finite,
                "both_qc_accepted": quality_ok,
                "finite_qc_rejected": finite & ~quality_ok,
                "contains_qc4": qc[[lower, upper]].eq(4).any(axis=1),
                "qc_lower": qc[lower],
                "qc_upper": qc[upper],
            },
            index=numeric.index,
        )
    return result


def simultaneous_temperature_wind(temperature, wind):
    """Joint support is the intersection of two same-layer, same-label masks."""
    result = {}
    for layer in LAYERS:
        ta, ws = temperature[layer], wind[layer]
        if not ta.index.equals(ws.index):
            raise ValueError("Temperature and speed labels must match exactly")
        mask = ta.eligible & ws.eligible
        result[layer] = pd.DataFrame(
            {
                "eligible": mask,
                "ta_difference": ta.difference.where(mask),
                "ta_gradient": ta.gradient.where(mask),
                "ws_difference": ws.difference.where(mask),
                "ws_gradient": ws.gradient.where(mask),
            },
            index=ta.index,
        )
    return result


def bin_specs(index, kind):
    """Enumerate empty bins too, preserving source clock labels."""
    if kind == "overall":
        return [({}, np.ones(len(index), dtype=bool))]
    if kind == "year":
        return [({"year": year}, index.year == year) for year in YEARS]
    if kind == "hour":
        return [({"hour": hour}, index.hour == hour) for hour in range(24)]
    if kind == "month_hour":
        return [
            ({"month": month, "hour": hour}, (index.month == month) & (index.hour == hour))
            for month, hour in product(range(1, 13), range(24))
        ]
    if kind == "quarter_hour":
        return [
            ({"quarter": quarter, "hour": hour}, (index.quarter == quarter) & (index.hour == hour))
            for quarter, hour in product(range(1, 5), (3, 9, 15, 21))
        ]
    raise ValueError(f"Unknown descriptive bin: {kind}")


def summarize(frame, kind, min_labels=MIN_LABELS):
    """Medians/IQR from matched labels; gate statistics, always keep raw n."""
    rows = []
    if not frame.index.is_unique:
        raise ValueError("Summary labels must be unique")
    for keys, selector in bin_specs(frame.index, kind):
        subset = frame.loc[selector, ["difference", "gradient"]].dropna()
        n = len(subset)
        row = {
            "scope": kind,
            **keys,
            "n_source_labels": int(np.sum(selector)),
            "n_eligible": n,
            "status": "ok" if n >= min_labels else f"fewer_than_{min_labels}_labels",
        }
        for column in ["difference", "gradient"]:
            row.update({f"{column}_{stat}": np.nan for stat in ["median", "q25", "q75", "iqr"]})
            if n >= min_labels:
                quantiles = subset[column].quantile([0.25, 0.5, 0.75])
                row.update(
                    {
                        f"{column}_median": quantiles.loc[0.5],
                        f"{column}_q25": quantiles.loc[0.25],
                        f"{column}_q75": quantiles.loc[0.75],
                        f"{column}_iqr": quantiles.loc[0.75] - quantiles.loc[0.25],
                    }
                )
        row["positive_difference_fraction"] = (
            float(subset.difference.gt(0).mean()) if n >= min_labels else np.nan
        )
        rows.append(row)
    return pd.DataFrame(rows)


def load_met(archive, start, end):
    """Full source selected numeric/QC fidelity versus independently parsed tokens."""
    fields = [exact_field(v, h) for v in VARIABLES for h in HEIGHTS]
    values_parts, quality_parts, coverage_rows, qc_rows, fidelity_rows = [], [], [], [], []
    with ZipFile(archive) as source:
        members = sorted(
            n for n in source.namelist() if n.startswith("MET_") and n.endswith(".csv")
        )
        if len(members) != 6:
            raise ValueError("Expected six MET source files for 2021-2026")
        for member in members:
            payload = source.read(member)
            frame = pd.read_csv(BytesIO(payload))
            tokens = pd.read_csv(BytesIO(payload), dtype=str, keep_default_na=False)
            index = pd.DatetimeIndex(pd.to_datetime(frame.Timestamp), name="Timestamp")
            if not index.is_unique or not index.is_monotonic_increasing:
                raise ValueError(f"Duplicate or unordered source labels: {member}")
            declared = (index >= start) & (index <= end)
            reference = index.year.isin(YEARS)
            vpart, qpart = pd.DataFrame(index=index), pd.DataFrame(index=index)
            for field in fields:
                qc_field = "QC_" + field.split("(")[0]
                if field not in frame or qc_field not in frame:
                    raise ValueError(f"Exact source field or QC absent: {member}: {field}")
                numeric = pd.to_numeric(frame[field], errors="coerce")
                numeric = numeric.where(np.isfinite(numeric) & numeric.ne(9999.9))
                qc = pd.to_numeric(frame[qc_field], errors="coerce")
                independent = pd.to_numeric(tokens[field], errors="coerce")
                independent = independent.where(np.isfinite(independent) & independent.ne(9999.9))
                independent_qc = pd.to_numeric(tokens[qc_field], errors="coerce")
                numeric_equal = bool(
                    np.array_equal(numeric.to_numpy(), independent.to_numpy(), equal_nan=True)
                )
                qc_equal = bool(
                    np.array_equal(qc.to_numpy(), independent_qc.to_numpy(), equal_nan=True)
                )
                # Both parses see every original label, including data outside declared/reference windows.
                fidelity_rows.append(
                    dict(
                        file=member,
                        field=field,
                        qc_field=qc_field,
                        source_labels=len(index),
                        numeric_equal=numeric_equal,
                        qc_equal=qc_equal,
                    )
                )
                vpart[field], qpart[field] = numeric.to_numpy(), qc.to_numpy()
                coverage_rows.append(
                    dict(
                        file=member,
                        field=field,
                        qc_field=qc_field,
                        year=int(index[0].year),
                        source_labels=len(index),
                        source_numeric=int(numeric.notna().sum()),
                        declared_labels=int(declared.sum()),
                        declared_numeric=int((numeric.notna() & declared).sum()),
                        outside_declared_numeric=int((numeric.notna() & ~declared).sum()),
                        reference_labels=int(reference.sum()),
                        reference_numeric=int((numeric.notna() & reference).sum()),
                        reference_numeric_qc0=int((numeric.notna() & reference & qc.eq(0)).sum()),
                        reference_numeric_qc4=int((numeric.notna() & reference & qc.eq(4)).sum()),
                    )
                )
                states = record_states(frame[field], 9999.9)
                qc_strings = qc.map(lambda x: "qc_missing" if pd.isna(x) else format(x, "g"))
                cells = pd.DataFrame({"qc": qc_strings, "record_state": states})
                for scope, selector in [
                    ("all_source", np.ones(len(index), dtype=bool)),
                    ("reference", reference),
                ]:
                    for (code, state), count in cells.loc[selector].value_counts().items():
                        qc_rows.append(
                            dict(
                                file=member,
                                field=field,
                                year=int(index[0].year),
                                scope=scope,
                                qc=code,
                                record_state=state,
                                count=int(count),
                            )
                        )
            values_parts.append(vpart)
            quality_parts.append(qpart)
    values, quality = pd.concat(values_parts), pd.concat(quality_parts)
    if not values.index.is_unique or not values.index.is_monotonic_increasing:
        raise ValueError("Source-year files overlap or are unordered")
    return (
        values,
        quality,
        pd.DataFrame(coverage_rows),
        pd.DataFrame(qc_rows),
        pd.DataFrame(fidelity_rows),
    )


def write_csv(name, frame, index=False):
    compression = {"method": "gzip", "mtime": 0} if name.endswith(".gz") else None
    frame.to_csv(OUT / name, index=index, encoding="utf-8-sig", compression=compression)


def eligibility_rows(variable, view, numeric, qc, pairs, profile_mask):
    rows, crosses = [], []
    for period, selector in [("2022-2025", np.ones(len(numeric), dtype=bool))] + [
        (str(year), numeric.index.year == year) for year in YEARS
    ]:
        for lower, upper in LAYERS:
            part = pairs[(lower, upper)].loc[selector]
            rows.append(
                dict(
                    view=view,
                    variable=variable,
                    support="pair",
                    period=period,
                    lower_m=lower,
                    upper_m=upper,
                    spacing_m=upper - lower,
                    n_source_labels=len(part),
                    n_all_finite=int(part.both_finite.sum()),
                    n_all_qc_accepted=int(part.both_qc_accepted.sum()),
                    n_eligible=int(part.eligible.sum()),
                    n_numeric_invalid=int((~part.both_finite).sum()),
                    n_finite_qc_rejected=int(part.finite_qc_rejected.sum()),
                    n_eligible_containing_qc4=int((part.eligible & part.contains_qc4).sum()),
                )
            )
            qc_frame = part[["qc_lower", "qc_upper"]].copy()
            for name in qc_frame:
                qc_frame[name] = qc_frame[name].map(
                    lambda x: "qc_missing" if pd.isna(x) else format(x, "g")
                )
            qc_frame["both_finite"] = part.both_finite.to_numpy()
            qc_frame["eligible"] = part.eligible.to_numpy()
            for keys, count in qc_frame.value_counts(dropna=False).items():
                crosses.append(
                    dict(
                        view=view,
                        variable=variable,
                        period=period,
                        lower_m=lower,
                        upper_m=upper,
                        qc_lower=keys[0],
                        qc_upper=keys[1],
                        both_finite=bool(keys[2]),
                        eligible=bool(keys[3]),
                        count=int(count),
                    )
                )
        finite = numeric.loc[selector].notna().all(axis=1)
        accepted = qc.loc[selector].isin(VIEWS[view]).all(axis=1)
        mask = profile_mask.loc[selector]
        rows.append(
            dict(
                view=view,
                variable=variable,
                support="full5",
                period=period,
                lower_m=1,
                upper_m=20,
                spacing_m=19,
                n_source_labels=int(np.sum(selector)),
                n_all_finite=int(finite.sum()),
                n_all_qc_accepted=int(accepted.sum()),
                n_eligible=int(mask.sum()),
                n_numeric_invalid=int((~finite).sum()),
                n_finite_qc_rejected=int((finite & ~accepted).sum()),
                n_eligible_containing_qc4=int((mask & qc.loc[selector].eq(4).any(axis=1)).sum()),
            )
        )
    return rows, crosses


def analyze(values, quality):
    reference = values.loc[values.index.year.isin(YEARS)]
    ref_qc = quality.loc[reference.index]
    summaries, profile_summaries, counts, crosses, joint_summaries, joint_counts = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    views_data = {}
    for view, allowed in VIEWS.items():
        pairs_by_variable, profiles_by_variable, masks_by_variable = {}, {}, {}
        hourly_profiles, hourly_pairs = (
            pd.DataFrame(index=reference.index),
            pd.DataFrame(index=reference.index),
        )
        for variable, (_, value_unit, gradient_unit) in VARIABLES.items():
            columns = [exact_field(variable, h) for h in HEIGHTS]
            numeric = reference[columns].set_axis(HEIGHTS, axis=1)
            qc = ref_qc[columns].set_axis(HEIGHTS, axis=1)
            selected, mask = eligible_profiles(numeric, qc, allowed)
            pairs = paired_gradients(numeric, qc, allowed)
            (
                pairs_by_variable[variable],
                profiles_by_variable[variable],
                masks_by_variable[variable],
            ) = pairs, selected, mask
            rows, pair_cross = eligibility_rows(variable, view, numeric, qc, pairs, mask)
            counts.extend(rows)
            crosses.extend(pair_cross)
            hourly_profiles[f"{variable}_full5_eligible"] = mask
            for height in HEIGHTS:
                hourly_profiles[f"{variable}_{height}m"] = selected[height]
                for scope in ["overall", "year", "hour", "quarter_hour"]:
                    # Reuse the exact shared profile mask at every height; no heightwise sample changes.
                    frame = pd.DataFrame(
                        {"difference": selected[height], "gradient": selected[height]}
                    )
                    stats = summarize(frame, scope).rename(
                        columns={
                            "difference_median": "value_median",
                            "difference_q25": "value_q25",
                            "difference_q75": "value_q75",
                            "difference_iqr": "value_iqr",
                        }
                    )
                    stats = stats.drop(
                        columns=[c for c in stats if c.startswith("gradient_")]
                        + ["positive_difference_fraction"]
                    )
                    stats = stats.assign(
                        view=view, variable=variable, height_m=height, value_unit=value_unit
                    )
                    profile_summaries.append(stats)
            for (lower, upper), pair in pairs.items():
                prefix = f"{variable}_{lower}_{upper}m"
                for column in ["difference", "gradient", "eligible"]:
                    hourly_pairs[f"{prefix}_{column}"] = pair[column]
                for scope in ["overall", "year", "hour", "month_hour"]:
                    stats = summarize(pair, scope).assign(
                        view=view,
                        variable=variable,
                        lower_m=lower,
                        upper_m=upper,
                        spacing_m=upper - lower,
                        difference_unit="percentage points" if variable == "RH" else value_unit,
                        gradient_unit=gradient_unit,
                    )
                    if variable != "Ta":
                        stats["positive_difference_fraction"] = np.nan
                    summaries.append(stats)
        joint = simultaneous_temperature_wind(pairs_by_variable["Ta"], pairs_by_variable["WS"])
        hourly_joint = pd.DataFrame(index=reference.index)
        for (lower, upper), part in joint.items():
            for name in part:
                hourly_joint[f"{lower}_{upper}m_{name}"] = part[name]
            for scope in ["overall", "year", "hour", "month_hour"]:
                ta_stats = summarize(
                    part.rename(columns={"ta_difference": "difference", "ta_gradient": "gradient"}),
                    scope,
                )
                ws_stats = summarize(
                    part.rename(columns={"ws_difference": "difference", "ws_gradient": "gradient"}),
                    scope,
                )
                for stat in ["median", "q25", "q75", "iqr"]:
                    ta_stats[f"ws_gradient_{stat}"] = ws_stats[f"gradient_{stat}"]
                    ta_stats[f"ws_difference_{stat}"] = ws_stats[f"difference_{stat}"]
                ta_stats = ta_stats.rename(
                    columns={
                        c: "ta_" + c
                        for c in ta_stats
                        if c.startswith("difference_")
                        or c.startswith("gradient_")
                        or c == "positive_difference_fraction"
                    }
                )
                joint_summaries.append(
                    ta_stats.assign(
                        view=view, lower_m=lower, upper_m=upper, spacing_m=upper - lower
                    )
                )
            for period, selector in [("2022-2025", np.ones(len(reference), dtype=bool))] + [
                (str(year), reference.index.year == year) for year in YEARS
            ]:
                ta_mask = pairs_by_variable["Ta"][(lower, upper)].eligible.loc[selector]
                ws_mask = pairs_by_variable["WS"][(lower, upper)].eligible.loc[selector]
                joint_counts.append(
                    dict(
                        view=view,
                        period=period,
                        lower_m=lower,
                        upper_m=upper,
                        n_source_labels=int(np.sum(selector)),
                        n_ta_only=int((ta_mask & ~ws_mask).sum()),
                        n_ws_only=int((~ta_mask & ws_mask).sum()),
                        n_neither=int((~ta_mask & ~ws_mask).sum()),
                        n_joint=int((ta_mask & ws_mask).sum()),
                    )
                )
        write_csv(f"full_height_profiles_{view}.csv.gz", hourly_profiles, index=True)
        write_csv(f"paired_gradients_{view}.csv.gz", hourly_pairs, index=True)
        write_csv(f"simultaneous_ta_ws_{view}.csv.gz", hourly_joint, index=True)
        views_data[view] = dict(
            profiles=profiles_by_variable,
            masks=masks_by_variable,
            pairs=pairs_by_variable,
            joint=joint,
        )
    return dict(
        gradient_summary=pd.concat(summaries, ignore_index=True),
        profile_summary=pd.concat(profile_summaries, ignore_index=True),
        eligibility_counts=pd.DataFrame(counts),
        pair_qc_counts=pd.DataFrame(crosses),
        joint_summary=pd.concat(joint_summaries, ignore_index=True),
        joint_eligibility_counts=pd.DataFrame(joint_counts),
        data=views_data,
    )


def sensitivity_comparison(summary):
    keys = ["variable", "scope", "year", "hour", "month", "lower_m", "upper_m"]
    left = summary.loc[summary.view.eq("qc0")].drop(columns="view")
    right = summary.loc[summary.view.eq("qc0_plus4")].drop(columns="view")
    comparison = left.merge(right, on=keys, suffixes=("_qc0", "_qc0_plus4"), validate="one_to_one")
    for col in ["n_eligible", "gradient_median", "positive_difference_fraction"]:
        comparison["delta_" + col] = comparison[col + "_qc0_plus4"] - comparison[col + "_qc0"]
    return comparison


def save_figure(fig, name):
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"{name}.{suffix}", dpi=160)
    plt.close(fig)


def make_figures(result):
    stats = result["gradient_summary"]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    colors = ["#285f8f", "#ec8546", "#379a80", "#8762a0", "#292d34"]
    for j, variable in enumerate(VARIABLES):
        for color, (lower, upper) in zip(colors, LAYERS):
            subset = stats.loc[
                stats.variable.eq(variable)
                & stats.scope.eq("hour")
                & stats.lower_m.eq(lower)
                & stats.upper_m.eq(upper)
            ]
            main = subset.loc[subset.view.eq("qc0")].sort_values("hour")
            broad = subset.loc[subset.view.eq("qc0_plus4")].sort_values("hour")
            axes[0, j].plot(main.hour, main.gradient_median, color=color, label=f"{lower}-{upper}m")
            axes[0, j].plot(broad.hour, broad.gradient_median, color=color, ls="--", alpha=0.65)
            axes[1, j].plot(main.hour, main.n_eligible, color=color)
        axes[0, j].axhline(0, color="gray", lw=0.7)
        axes[0, j].set(
            title=f"{variable}: median simultaneous gradient", ylabel=VARIABLES[variable][2]
        )
        axes[1, j].set(ylabel="QC0 paired labels n", xlabel="Beijing wall-clock hour (UTC+8)")
        axes[1, j].yaxis.set_major_locator(MaxNLocator(integer=True))
        for ax in axes[:, j]:
            ax.set_xticks([0, 3, 6, 9, 12, 15, 18, 21, 23])
            ax.grid(alpha=0.2)
    axes[0, 0].legend(ncol=2, fontsize=8)
    fig.suptitle(
        "2022-2025 wall-clock cycles; solid QC0, dashed independent QC0+4\n30-label display gate; n is not independent sample size; speed gradient is scalar"
    )
    save_figure(fig, "clock_cycles")

    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    for row, variable in enumerate(["Ta", "WS"]):
        for col, layer in enumerate([(1, 2), (4, 10), (2, 20)]):
            part = stats.loc[
                stats.variable.eq(variable)
                & stats.view.eq("qc0")
                & stats.scope.eq("month_hour")
                & stats.lower_m.eq(layer[0])
                & stats.upper_m.eq(layer[1])
            ]
            matrix = part.pivot(index="month", columns="hour", values="gradient_median").reindex(
                index=range(1, 13), columns=range(24)
            )
            finite = matrix.to_numpy()[np.isfinite(matrix.to_numpy())]
            limit = max(float(np.max(np.abs(finite))) if len(finite) else 0, 1e-6)
            artist = axes[row, col].imshow(
                matrix.to_numpy(),
                aspect="auto",
                origin="lower",
                cmap="RdBu_r",
                norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit),
                extent=(-0.5, 23.5, 0.5, 12.5),
            )
            axes[row, col].set(
                title=f"{variable} {layer[0]}-{layer[1]}m",
                xlabel="UTC+8 clock hour",
                ylabel="Calendar month",
                yticks=[1, 3, 6, 9, 12],
                xticks=[0, 6, 12, 18, 23],
            )
            fig.colorbar(artist, ax=axes[row, col], label=VARIABLES[variable][2], shrink=0.8)
    fig.suptitle(
        "QC0 median gradients by month and wall-clock hour, 2022-2025\nThree preselected layers; separate panel scales; bins n<30 blank; all five layers in CSV"
    )
    save_figure(fig, "monthly_clock_gradients")

    profiles = result["profile_summary"]
    fig, axes = plt.subplots(3, 4, figsize=(15, 10), constrained_layout=True, sharey=True)
    clock_colors = {3: "#254d83", 9: "#43a18e", 15: "#d5653f", 21: "#8866a0"}
    for i, variable in enumerate(VARIABLES):
        for j, quarter in enumerate(range(1, 5)):
            for hour, color in clock_colors.items():
                subset = profiles.loc[
                    profiles.variable.eq(variable)
                    & profiles.scope.eq("quarter_hour")
                    & profiles.quarter.eq(quarter)
                    & profiles.hour.eq(hour)
                ]
                main = subset.loc[subset.view.eq("qc0")].sort_values("height_m")
                broad = subset.loc[subset.view.eq("qc0_plus4")].sort_values("height_m")
                n = int(main.n_eligible.iloc[0]) if len(main) else 0
                axes[i, j].plot(
                    main.value_median,
                    main.height_m,
                    marker="o",
                    ms=3,
                    color=color,
                    label=f"{hour:02d}:00 n={n}",
                )
                axes[i, j].plot(broad.value_median, broad.height_m, ls="--", color=color, alpha=0.6)
            axes[i, j].set(
                title=f"{variable}, calendar Q{quarter}",
                xlabel=VARIABLES[variable][1],
                yticks=HEIGHTS,
            )
            axes[i, j].grid(alpha=0.2)
            axes[i, j].legend(fontsize=7)
        axes[i, 0].set_ylabel("Height (m)")
    fig.suptitle(
        "Full five-height profiles on shared same-label support, 2022-2025\nSolid QC0; dashed independent QC0+4; n applies to all five heights; quarters are calendar bins"
    )
    save_figure(fig, "selected_full_profiles")


def data_checks(values, quality, coverage, cross, fidelity, result, config_hash, hashes, manifest):
    reference = values.loc[values.index.year.isin(YEARS)]
    counts = result["eligibility_counts"]
    joint_counts = result["joint_eligibility_counts"]
    stats = result["gradient_summary"]
    profiles = result["profile_summary"]
    exact = pd.date_range("2022-01-01", "2025-12-31 23:00", freq="h", name="Timestamp")
    full_profiles_valid, pair_exact, independent_views, shared_counts = True, True, True, True
    joint_exact, sensitivity_nested = True, True
    for view, allowed in VIEWS.items():
        for variable in VARIABLES:
            fields = [exact_field(variable, h) for h in HEIGHTS]
            raw = reference[fields].set_axis(HEIGHTS, axis=1)
            qc = quality.loc[reference.index, fields].set_axis(HEIGHTS, axis=1)
            raw = raw.where(np.isfinite(raw) & raw.ne(9999.9))
            mask = (raw.notna() & qc.isin(allowed)).all(axis=1)
            selected = result["data"][view]["profiles"][variable]
            full_profiles_valid &= bool(selected.notna().all(axis=1).equals(mask))
            full_profiles_valid &= bool(selected.loc[mask].equals(raw.loc[mask]))
            for lower, upper in LAYERS:
                expected = raw[[lower, upper]].notna().all(axis=1) & qc[[lower, upper]].isin(
                    allowed
                ).all(axis=1)
                paired = result["data"][view]["pairs"][variable][(lower, upper)]
                independent_views &= bool(expected.equals(paired.eligible))
                pair_exact &= bool(
                    np.allclose(
                        paired.gradient.loc[expected],
                        (raw[upper] - raw[lower]).loc[expected] / (upper - lower),
                        rtol=0,
                        atol=0,
                    )
                )
            # Full5 curves must use one common count at every height in each bin.
            part = profiles.loc[profiles.view.eq(view) & profiles.variable.eq(variable)]
            shared_counts &= bool(
                part.groupby(["scope", "year", "hour", "quarter"], dropna=False)
                .n_eligible.nunique()
                .eq(1)
                .all()
            )
        for layer in LAYERS:
            ta = result["data"][view]["pairs"]["Ta"][layer]
            ws = result["data"][view]["pairs"]["WS"][layer]
            joint = result["data"][view]["joint"][layer]
            joint_mask = ta.eligible & ws.eligible
            joint_exact &= bool(joint.eligible.equals(joint_mask))
            joint_exact &= bool(joint.ta_gradient.equals(ta.gradient.where(joint_mask)))
            joint_exact &= bool(joint.ws_gradient.equals(ws.gradient.where(joint_mask)))
    for variable in VARIABLES:
        strict, broad = result["data"]["qc0"], result["data"]["qc0_plus4"]
        sensitivity_nested &= bool((~strict["masks"][variable] | broad["masks"][variable]).all())
        for layer in LAYERS:
            a, b = strict["pairs"][variable][layer], broad["pairs"][variable][layer]
            sensitivity_nested &= bool((~a.eligible | b.eligible).all())
            sensitivity_nested &= bool(
                a.gradient.loc[a.eligible].equals(b.gradient.loc[a.eligible])
            )
    yearly = (
        counts.loc[counts.period.ne("2022-2025")]
        .groupby(["view", "variable", "support", "lower_m", "upper_m"])
        .n_eligible.sum()
    )
    total = (
        counts.loc[counts.period.eq("2022-2025")]
        .set_index(["view", "variable", "support", "lower_m", "upper_m"])
        .n_eligible
    )
    pair_total = counts.loc[
        counts.period.eq("2022-2025") & counts.support.eq("pair"), "n_eligible"
    ].sum()
    hourly = stats.loc[stats.scope.eq("hour")].n_eligible.sum()
    monthly = stats.loc[stats.scope.eq("month_hour")].n_eligible.sum()
    joint_stats = result["joint_summary"]
    joint_n = int(joint_counts.loc[joint_counts.period.eq("2022-2025"), "n_joint"].sum())
    return {
        "all_8_archive_hashes_unchanged": len(manifest) == 8
        and all(
            sha256(ROOT / item["path"]) == hashes[item["path"]] == item["sha256"]
            for item in manifest
        ),
        "constraints_unchanged": sha256(ROOT / "config/analysis-constraints.yml") == config_hash,
        "15_fields_90_field_years_full_source_numeric_fidelity": len(fidelity) == 90
        and bool(fidelity.numeric_equal.all()),
        "90_field_years_full_source_qc_fidelity": len(fidelity) == 90
        and bool(fidelity.qc_equal.all()),
        "full_source_qc_cross_counts_reconcile": int(
            cross.loc[cross.scope.eq("all_source"), "count"].sum()
        )
        == int(coverage.source_labels.sum()),
        "reference_qc_cross_counts_reconcile": int(
            cross.loc[cross.scope.eq("reference"), "count"].sum()
        )
        == int(coverage.reference_labels.sum()),
        "numeric_declared_outside_partition": bool(
            coverage.source_numeric.eq(
                coverage.declared_numeric + coverage.outside_declared_numeric
            ).all()
        ),
        "reference_is_35064_unique_hour_labels": reference.index.equals(exact)
        and len(reference) == 35064,
        "full5_values_exactly_preserved_on_shared_support": full_profiles_valid,
        "full5_bin_counts_identical_at_all_heights": shared_counts,
        "each_qc_view_independently_matches_raw_pair_eligibility": independent_views,
        "simultaneous_gradients_use_exact_height_spacing": pair_exact,
        "eligibility_reasons_partition_all_labels": bool(
            counts.n_source_labels.eq(
                counts.n_eligible + counts.n_numeric_invalid + counts.n_finite_qc_rejected
            ).all()
        ),
        "year_counts_reconcile_with_total": bool(yearly.sort_index().equals(total.sort_index())),
        "hour_and_month_hour_counts_reconcile": int(pair_total) == int(hourly) == int(monthly),
        "joint_support_categories_partition_all_labels": bool(
            joint_counts.n_source_labels.eq(
                joint_counts[["n_ta_only", "n_ws_only", "n_neither", "n_joint"]].sum(axis=1)
            ).all()
        ),
        "joint_temperature_speed_values_and_masks_exact": joint_exact,
        "joint_hour_month_hour_and_total_counts_reconcile": joint_n
        == int(joint_stats.loc[joint_stats.scope.eq("overall"), "n_eligible"].sum())
        == int(joint_stats.loc[joint_stats.scope.eq("hour"), "n_eligible"].sum())
        == int(joint_stats.loc[joint_stats.scope.eq("month_hour"), "n_eligible"].sum()),
        "qc4_adds_support_without_changing_common_numeric_values": sensitivity_nested,
        "pair_qc_cross_counts_reconcile": int(result["pair_qc_counts"]["count"].sum())
        == int(counts.loc[counts.support.eq("pair"), "n_source_labels"].sum()),
        "no_statistics_shown_below_30_label_gate": bool(
            stats.loc[
                stats.n_eligible.lt(MIN_LABELS),
                ["gradient_median", "difference_median", "positive_difference_fraction"],
            ]
            .isna()
            .all()
            .all()
        ),
        "positive_temperature_fraction_between_0_and_1": bool(
            stats.loc[stats.variable.eq("Ta"), "positive_difference_fraction"]
            .dropna()
            .between(0, 1)
            .all()
        ),
        "only_Ta_WS_RH_no_rain_FLUX_or_event_labels": set(values.columns)
        == {exact_field(v, h) for v in VARIABLES for h in HEIGHTS},
    }


def build_report(result, coverage, fidelity, verification):
    counts, stats = result["eligibility_counts"], result["gradient_summary"]
    totals = counts.loc[counts.period.eq("2022-2025")]
    rows = []
    for variable in VARIABLES:
        strict = totals.loc[
            totals.variable.eq(variable) & totals.view.eq("qc0") & totals.support.eq("full5")
        ].iloc[0]
        broad = totals.loc[
            totals.variable.eq(variable) & totals.view.eq("qc0_plus4") & totals.support.eq("full5")
        ].iloc[0]
        rows.append(
            f"| {variable} | {strict.n_eligible:,} | {broad.n_eligible:,} | {broad.n_eligible - strict.n_eligible:,} |"
        )
    layer_rows = []
    for variable in VARIABLES:
        for lower, upper in LAYERS:
            subset = stats.loc[
                stats.variable.eq(variable)
                & stats.scope.eq("overall")
                & stats.lower_m.eq(lower)
                & stats.upper_m.eq(upper)
            ]
            main = subset.loc[subset.view.eq("qc0")].iloc[0]
            sensitivity = subset.loc[subset.view.eq("qc0_plus4")].iloc[0]
            fraction = f"{main.positive_difference_fraction:.2%}" if variable == "Ta" else "—"
            layer_rows.append(
                f"| {variable} | {lower}–{upper} | {main.n_eligible:,} | {main.gradient_median:.6f} | "
                f"{main.gradient_q25:.6f}～{main.gradient_q75:.6f} | {fraction} | {sensitivity.n_eligible - main.n_eligible:,} | "
                f"{sensitivity.gradient_median - main.gradient_median:+.6f} |"
            )
    cycle_rows = []
    for variable in ["Ta", "WS"]:
        part = stats.loc[
            stats.variable.eq(variable)
            & stats.view.eq("qc0")
            & stats.scope.eq("hour")
            & stats.lower_m.eq(2)
            & stats.upper_m.eq(20)
        ]
        low, high = part.loc[part.gradient_median.idxmin()], part.loc[part.gradient_median.idxmax()]
        cycle_rows.append(
            f"| {variable} 2–20m | {int(low.hour):02d}:00 | {low.gradient_median:.6f} | "
            f"{int(high.hour):02d}:00 | {high.gradient_median:.6f} | {int(part.n_eligible.min())}～{int(part.n_eligible.max())} |"
        )
    joint_rows = []
    for row in (
        result["joint_eligibility_counts"]
        .loc[
            result["joint_eligibility_counts"].period.eq("2022-2025")
            & result["joint_eligibility_counts"].view.eq("qc0")
        ]
        .itertuples(index=False)
    ):
        joint_rows.append(
            f"| {row.lower_m}–{row.upper_m} | {row.n_joint:,} | {row.n_ta_only:,} | {row.n_ws_only:,} | {row.n_neither:,} |"
        )
    fields = "\n".join(
        f"| {v} | {h} | `{exact_field(v, h)}` | `QC_{v}_{h}m` | {VARIABLES[v][1]} |"
        for v in VARIABLES
        for h in HEIGHTS
    )
    reference = coverage.loc[coverage.year.isin(YEARS)]
    report = f"""# 第一问前置探索：同步垂直剖面与钟点结构

生成：{verification["checked_at_utc"]}。这是区域气象背景描述，未完成灾害关联或极端过程识别，不输出最终前5因素。
F=原记录/表头、已核实官方定义及可复算样本统计；I=描述性解释；U=尚缺证据。官方依据见[元数据复核](metadata-review.md)，前一步见[变量关系](variable-relations.md)。

## 1. 时段、字段与方法（F）

参考窗为2022—2025四个完整公历年，共1461日、35,064个小时标签；完整年只指参考日历，不保证观测齐全。
使用原始MET的Ta、WS、RH各1/2/4/10/20m，共15字段。不读入降水、FLUX或灾害时间标签。
精确字段、QC和单位如下；从表头解释高度，不假定仪器误差、垂直基准或暴露已知。

| 变量 | 高度m | 原字段 | 对应QC | 数值单位 |
| --- | --- | --- | --- | --- |
{fields}

源时间标签为北京时间UTC+8；不移时、不按经纬度推算太阳时。平均支持区间及标签代表起点/终点/中心均U。
站点纬度28.86/28.26°N冲突未解，不能给03/09/15/21时等钟点赋真实昼夜标签。
本报告“日变化/钟点结构”只指墙上时钟小时分组；公历季度Q1—Q4不是已确定的气候季节。

主视图仅QC0；QC0+4直接从同一原源独立生成，4按提供方定义为插补数据，只作敏感性比较；最终QC政策仍U。
过滤仅发生在本轮派生描述视图：数值解析失败、9999.9、±inf不入统计，保留0和其余原值，不新增插补、不裁剪、不删除原记录。
RH若超100%仍保留原值与QC，既有范围告警并非自动删除政策。

每变量全高剖面先要求同一标签的五高度全部有限且满足该视图QC，再在共同标签上逐高度汇总；不能用各高度各自有效样本拼接剖面。
每层差值先在同时刻计算ΔX=X上−X下，再除实际高度差Δz；层为1–2、2–4、4–10、10–20及2–20m，对应Δz=1、2、6、10、18m。
层内两高度分别共同有效，故每层的n允许不同，也不强制等于全高n。差值中位数来自逐标签差值，不是两个独立中位数相减。
另以同层温差和风速差各自合格标签的交集输出Ta+WS同时描述，不把它们各自不同n的统计量冒作共同支持。

按总体、逐年、24钟点、12月×24钟点输出差值与梯度的中位数、Q25、Q75、IQR；选定剖面按公历季度×03/09/15/21时输出。
每格n≥30才展示统计量，n和源标签分母始终保留，包括空格；30是本轮透明描述展示门槛，不是官方QC标准或独立样本量。
同一格由四年同月/钟点标签汇集，不先计算日中位数，不将日/月权重重新等化。不同缺测覆盖可影响表观钟点差异，不能据此作机制判断。
中位数曲线是样本分布的逐高度汇总，未必对应任一真实单个时刻；IQR是样本分布范围，不是置信区间。

## 2. 共享覆盖与同层统计（F）

15字段参考窗共有{int(reference.reference_labels.sum()):,}个标签×字段单元格，有限数值{int(reference.reference_numeric.sum()):,}个，
QC0有限数值{int(reference.reference_numeric_qc0.sum()):,}个、QC4有限数值{int(reference.reference_numeric_qc4.sum()):,}个。
全高剖面的共同标签数如下，每变量的五条高度均共享同一mask：

| 变量 | QC0全高共同n | QC0+4全高共同n | 增加n |
| --- | --- | --- | --- |
{chr(10).join(rows)}

下表为同时刻逐层梯度。Ta为℃/m，WS为(m/s)/m，RH为百分点/m；IQR列展示Q25～Q75边界。
Δn与Δ中位数为独立QC0+4减QC0，不作为最终QC裁决。

| 变量 | 层m | QC0配对n | 梯度中位数 | Q25～Q75 | ΔTa>0比例 | Δn | Δ梯度中位数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(layer_rows)}

ΔTa>0比例的分母是该格同时刻合格温度配对标签数，严格大于0，0不计正值。
这仅为上层观测温度较高现象；未换算位温、没有压力高度及湿度/误差条件，不能直接称为静力稳定度、位温逆温或边界层稳定度。
WS梯度是标量风速差/高度差，不是风矢量切变、湍流强度、Richardson数或稳定性指标；未使用风向。
RH梯度是相对湿度的百分点/m，不是绝对湿度或水汽含量梯度。

Ta+WS共同支持的QC0总计如下；其他变量各自n见配对表，不进行独立样本显著性、置信区间或因果排序。

| 层m | 温度与风速共同n | 仅温度合格 | 仅风速合格 | 均不合格 |
| --- | --- | --- | --- | --- |
{chr(10).join(joint_rows)}

## 3. 钟点与月份结构（F/I）

2–20m总体钟点中位梯度的最低/最高钟点如下，仅是24个预定钟点格的样本内描述，不作真实昼夜或气候规律的显著性断言。

| 变量/层 | 最低钟点 | 梯度 | 最高钟点 | 梯度 | 各钟点QC0配对n范围 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(cycle_rows)}

![钟点循环及配对覆盖](../output/vertical_profiles/clock_cycles.png)

![月份×钟点温度与标量风速梯度](../output/vertical_profiles/monthly_clock_gradients.png)

![公历季度与选定钟点全高剖面](../output/vertical_profiles/selected_full_profiles.png)

I：不同月份与钟点的梯度分布及全高形态有样本内差异；必须结合每格覆盖、QC视图和仪器误差讨论。
不能把这种分组差异归因于太阳辐射、湍流混合或灾害触发；月×钟点图的每面板独立色标，跨面板颜色不代表同一数值。
曲线虚线是QC0+4独立计算；相近不证明插补无影响或源观测无偏。全部逐年与每格敏感性对比见机器表。

## 4. 证据边界与下一步（U）

| 已有F或有限I | 需要补充的U |
| --- | --- |
| 多高度同时刻温、湿、标量风速剖面和层间差值 | 仪器型号/精度/校准、同钟同步性、支架/暴露、名义高度实际变化、源QC处理与QC4插补方式 |
| 官方UTC+8及小时标签连续覆盖 | 各字段真实平均支持区间、时间标签相位；不同变量是否完全同一观测支持 |
| ΔTa>0观测现象 | 各高度压力或可靠位温条件、湿度及测量误差；当前不能给稳定度结论 |
| 站点背景及墙钟小时结构 | 纬度冲突正式澄清、坐标/地形代表性；随后才可定义太阳时昼夜和局地代表性 |
| Ta与WS同标签共同支持计数 | 风向的圆周统计、矢量坐标与仪器方向；才可另定义矢量切变或相关量 |
| 参考年内分布与逐年计数 | 独立过程单位、事件/对照及时间阶段、源区观测；才可进行极端过程或灾害关联及因素排序 |

FLUX仍保留在总体证据链中，本轮未进入剖面；后续可单独做其原记录/缺段/量纲核验，不能给缺失QC默认赋0。
降水累计区间、清零语义仍未确认，本轮无降水累计/滚动/强度特征；无训练、标签或最终前5因素。

## 5. 产物、复现与核验（F）

运行：`conda run -n mc-base --no-capture-output python scripts/analyze_vertical_profiles.py`。
测试：`conda run -n mc-base --no-capture-output python -m unittest discover -s tests -p test_vertical_profiles.py -v`。
路径由脚本自身位置定位项目根；先前审计/元数据下载目录的历史绝对路径仅为证据，不是运行依赖。
观测窗口通过`project_runtime.load_observation_window()`读取版本化事实快照；现存官方缓存仅交叉核对，不依赖其存在。

- `selected_fields.csv`：15个精确原字段/QC/高度/单位。
- `source_coverage.csv`、`source_qc_counts.csv`、`source_fidelity.csv`：六年所有源标签逐字段数值/QC保真、源窗/参考窗计数，声明窗外数值单列保留。
- `full_height_profiles_*.csv.gz`：参考窗每个标签的全高共同mask和原值；mask外留缺，不补齐。
- `paired_gradients_*.csv.gz`：每层每变量同标签差值/梯度/合格mask；`simultaneous_ta_ws_*.csv.gz`：两变量同层交集mask及原差值/梯度。
- `eligibility_counts.csv`：两视图×变量×层/全高×总体/逐年的标签分母、有限值、QC合格、数值无效、数值有限但QC不入视图、含QC4计数。
- `pair_qc_counts.csv`：各层两高度原QC组合×是否均有限×是否合格计数；未把不合格源记录删除。
- `gradient_summary.csv`、`profile_summary.csv`：所有统计格的n、门槛状态、中位数和IQR；`joint_summary.csv`、`joint_eligibility_counts.csv`：Ta+WS共同支持；`sensitivity_comparison.csv`：独立QC视图逐格并列。
- 三幅图均保存PNG和SVG；CSV为UTF-8 BOM，gzip表可用pandas直接读取。所有记录路径为项目根相对路径。

`verification.json`中{sum(verification["checks"].values())}/{len(verification["checks"])}项数据检查通过；
8个原包SHA-256与约束前后不变，15字段×6年共{len(fidelity)}字段年、{int(fidelity.source_labels.sum()):,}源测量单元格（含缺测）及同数QC单元格逐格与词元独立读取互校。
每格n及年度总计守恒，全高共享支持、真实高度差、两QC视图独立准入均有核验；这不验证科学假设、稳定度、灾害机制或预测性能。
合成测试先观察缺实现失败，再实现覆盖同步差值与分开中位数之差、真实间距、QC4/不插补、缺高度/轴不匹配及分箱计数。
"""
    (ROOT / "docs/vertical-profiles.md").write_text(report, encoding="utf-8")


def main():
    from project_runtime import load_observation_window, verify_input_files

    OUT.mkdir(parents=True, exist_ok=True)
    config_path = ROOT / "config/analysis-constraints.yml"
    config_hash = sha256(config_path)
    constraints = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if constraints["hourly_observations"]["official_missing_value"] != 9999.9:
        raise ValueError("Review required: official missing code changed")
    if (
        constraints["prediction"]["final_time_labels"] != "deferred"
        or constraints["precipitation"]["final_rolling_features"] != "deferred"
    ):
        raise ValueError("Bounded descriptive analysis requires deferred labels and rain features")
    start, end, evidence = load_observation_window()
    manifest_path = ROOT / "config/input-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))["archives"]
    hashes = verify_input_files()
    archive = next(ROOT / item["path"] for item in manifest if item["attachment"] == 1)
    values, quality, coverage, cross, fidelity = load_met(archive, start, end)
    fields = pd.DataFrame(
        [
            dict(
                variable=v,
                height_m=h,
                field=exact_field(v, h),
                qc_field=f"QC_{v}_{h}m",
                value_unit=VARIABLES[v][1],
                gradient_unit=VARIABLES[v][2],
            )
            for v in VARIABLES
            for h in HEIGHTS
        ]
    )
    for name, frame in [
        ("selected_fields.csv", fields),
        ("source_coverage.csv", coverage),
        ("source_qc_counts.csv", cross),
        ("source_fidelity.csv", fidelity),
    ]:
        write_csv(name, frame)
    result = analyze(values, quality)
    result["sensitivity_comparison"] = sensitivity_comparison(result["gradient_summary"])
    for name, frame in result.items():
        if isinstance(frame, pd.DataFrame):
            write_csv(name + ".csv", frame)
    checks = data_checks(
        values, quality, coverage, cross, fidelity, result, config_hash, hashes, manifest
    )
    verification = dict(
        passed=all(checks.values()),
        checked_at_utc=datetime.now(timezone.utc).isoformat(),
        checks=checks,
        source_hashes=hashes,
        constraints_file="config/analysis-constraints.yml",
        constraints_sha256=config_hash,
        input_manifest_file="config/input-manifest.json",
        input_manifest_sha256=sha256(manifest_path),
        observation_reference=evidence,
        declared_label_window={"start": str(start), "end": str(end), "timezone": "UTC+8"},
        reference_years=list(YEARS),
        descriptive_min_labels=MIN_LABELS,
        fidelity_numeric_cells=int(fidelity.source_labels.sum()),
        fidelity_qc_cells=int(fidelity.source_labels.sum()),
        policies=dict(
            raw_writes=False,
            new_imputation=False,
            source_deletion=False,
            rainfall_features=False,
            event_labels=False,
            training=False,
            stability_claims=False,
            causal_ranking=False,
        ),
    )
    (OUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not verification["passed"]:
        raise SystemExit("Vertical-profile data checks failed; inspect verification.json")
    make_figures(result)
    build_report(result, coverage, fidelity, verification)
    print("Vertical profiles complete: output/vertical_profiles/", flush=True)


if __name__ == "__main__":
    main()
