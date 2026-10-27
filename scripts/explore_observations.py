"""无标签观测探索：原包只读，统计视图不等于最终QC政策。

运行：conda run -n mc-base --no-capture-output python scripts/explore_observations.py
覆盖窗来自已存档官网元数据，不假定仪器在整个窗口持续运行。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from audit_tabular import range_flags
from project_runtime import load_observation_window

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/observation_exploration"
TAB = ROOT / "output/data_audit/tabular"
STATE_NAMES = ["native_missing", "nonnumeric", "official_missing", "nonfinite", "finite_record"]


def declared_window(detail: dict, exported: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    """正常详情给出日期文本，导出为epoch毫秒；显式互校，不猜测整数单位。"""
    labels = tuple(pd.Timestamp(detail[key]) for key in ["startTime", "endTime"])
    epochs = tuple(
        pd.to_datetime(exported[key], unit="ms", utc=True)
        .tz_convert("Asia/Shanghai")
        .tz_localize(None)
        for key in ["startTime", "endTime"]
    )
    if labels != epochs:
        raise ValueError("Catalog detail dates disagree with millisecond export in UTC+8")
    return labels


def in_declared_window(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp):
    """两端均为原始标签；不扩展成未知的小时统计区间。"""
    return (index >= start) & (index <= end)


def record_states(raw: pd.Series, missing_code: float) -> pd.Series:
    """native_missing包括read_csv识别的字面NaN，不意味着源CSV存在空白词元。"""
    numeric = pd.to_numeric(raw, errors="coerce")
    result = pd.Series("finite_record", index=raw.index)
    result.loc[numeric.notna() & ~np.isfinite(numeric)] = "nonfinite"
    result.loc[numeric.eq(missing_code)] = "official_missing"
    result.loc[raw.notna() & numeric.isna()] = "nonnumeric"
    result.loc[raw.isna()] = "native_missing"
    return result


def qc_labels(frame: pd.DataFrame, field: str) -> pd.Series:
    lookup = {name.lower(): name for name in frame.columns}
    qc_field = lookup.get(("QC_" + field.split("(")[0]).lower())
    if qc_field is None:
        return pd.Series("not_provided", index=frame.index)

    def label(value):
        if pd.isna(value):
            return "qc_missing"
        try:
            return format(float(value), "g")
        except (TypeError, ValueError):
            return str(value)

    return frame[qc_field].map(label)


def missing_runs(values: pd.Series) -> list[dict]:
    """连续缺测按小时标签计数，含跨年缺段；区间端点不代表观测支持区间。"""
    if len(values) == 0:
        return []
    if (
        len(values) > 1
        and not (values.index.to_series().diff().iloc[1:] == pd.Timedelta(hours=1)).all()
    ):
        raise ValueError("Missing-run input must have a complete hourly label index")
    mask = values.isna().to_numpy()
    changes = np.diff(np.r_[False, mask, False].astype(int))
    runs = []
    for first, stop in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
        position = (
            "entire_window"
            if first == 0 and stop == len(values)
            else "leading"
            if first == 0
            else "trailing"
            if stop == len(values)
            else "internal"
        )
        runs.append(
            {
                "start_label": str(values.index[first]),
                "end_label": str(values.index[stop - 1]),
                "hours": int(stop - first),
                "position": position,
            }
        )
    return runs


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(name: str, rows) -> pd.DataFrame:
    result = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    result.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    return result


def audit_records(archive: Path, start, end, missing_code) -> dict:
    yearly, cross, monthly, contexts, runs, field_summary, outside, label_coverage = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    pieces = {}
    with ZipFile(archive) as source:
        for member in sorted(n for n in source.namelist() if n.endswith(".csv")):
            payload = source.read(member)
            frame = pd.read_csv(BytesIO(payload))
            tokens = pd.read_csv(BytesIO(payload), dtype=str, keep_default_na=False)
            group = member.split("_")[0]
            times = pd.DatetimeIndex(pd.to_datetime(frame.Timestamp))
            assert times.is_unique and times.is_monotonic_increasing
            declared = in_declared_window(times, start, end)
            fields = [f for f in frame if f != "Timestamp" and not f.startswith("QC_")]
            for field in fields:
                states = record_states(frame[field], missing_code)
                numeric = pd.to_numeric(frame[field], errors="coerce")
                diagnostic = numeric.where(states.eq("finite_record"))
                quality = qc_labels(frame, field)
                has_qc = bool((quality != "not_provided").any())
                flagged = range_flags(field, diagnostic)
                for at in np.flatnonzero((states.eq("finite_record") & ~declared).to_numpy()):
                    outside.append(
                        {
                            "group": group,
                            "file": member,
                            "field": field,
                            "label": str(times[at]),
                            "source_token": tokens[field].iloc[at],
                            "qc": quality.iloc[at],
                            "scope": "before_declared_start"
                            if times[at] < start
                            else "after_declared_end",
                        }
                    )
                row = {
                    "file": member,
                    "group": group,
                    "year": int(times[0].year),
                    "field": field,
                    "calendar_labels": len(frame),
                    "declared_labels": int(declared.sum()),
                    "outside_declared_labels": int((~declared).sum()),
                    "calendar_finite": int(states.eq("finite_record").sum()),
                    "declared_finite": int((states.eq("finite_record") & declared).sum()),
                    "outside_declared_finite": int((states.eq("finite_record") & ~declared).sum()),
                    "qc_provided": has_qc,
                    "qc0_numeric": int(
                        (quality.eq("0") & states.eq("finite_record") & declared).sum()
                    ),
                    "qc4_numeric": int(
                        (quality.eq("4") & states.eq("finite_record") & declared).sum()
                    ),
                    "range_flags_declared": int((flagged & declared).sum()),
                }
                row.update({s: int((states.eq(s) & declared).sum()) for s in STATE_NAMES})
                yearly.append(row)
                part = pd.DataFrame(
                    {
                        "qc": quality.loc[declared],
                        "record_state": states.loc[declared],
                        "range_flag": flagged.loc[declared],
                    }
                )
                for (code, state), small in part.groupby(["qc", "record_state"]):
                    cross.append(
                        {
                            "group": group,
                            "year": row["year"],
                            "field": field,
                            "qc": code,
                            "record_state": state,
                            "count": len(small),
                            "range_flags": int(small.range_flag.sum()),
                        }
                    )
                # 仅将描述性统计的空值掩膜另存，不回写原值、不累计降水。
                series = pd.Series(diagnostic.loc[declared].to_numpy(), index=times[declared])
                pieces.setdefault((group, field), []).append(series)
                for month, small in series.groupby(series.index.to_period("M")):
                    vals = small.dropna()
                    monthly.append(
                        {
                            "group": group,
                            "field": field,
                            "month": str(month),
                            "labels": len(small),
                            "finite_records": len(vals),
                            "missing_fraction": float(small.isna().mean()),
                            "median": float(vals.median()) if len(vals) else None,
                            "q25": float(vals.quantile(0.25)) if len(vals) else None,
                            "q75": float(vals.quantile(0.75)) if len(vals) else None,
                        }
                    )
                for at in np.flatnonzero((flagged & declared).to_numpy()):
                    for k in range(max(0, at - 2), min(len(frame), at + 3)):
                        contexts.append(
                            {
                                "group": group,
                                "file": member,
                                "field": field,
                                "flag_label": str(times[at]),
                                "label": str(times[k]),
                                "offset_records": k - at,
                                "source_token": tokens[field].iloc[k],
                                "numeric_value": numeric.iloc[k],
                                "record_state": states.iloc[k],
                                "qc": quality.iloc[k],
                                "is_range_flag": bool(flagged.iloc[k]),
                            }
                        )
            all_numeric = frame[fields].apply(pd.to_numeric, errors="coerce")
            usable = (
                all_numeric.notna() & np.isfinite(all_numeric) & all_numeric.ne(missing_code)
            ).loc[declared]
            per_label_count = usable.sum(axis=1)
            label_coverage.append(
                {
                    "group": group,
                    "year": int(times[0].year),
                    "fields": len(fields),
                    "declared_hour_labels": len(usable),
                    "all_fields_numeric_labels": int(per_label_count.eq(len(fields)).sum()),
                    "all_fields_missing_labels": int(per_label_count.eq(0).sum()),
                    "partial_numeric_labels": int(
                        per_label_count.between(1, len(fields) - 1).sum()
                    ),
                    "finite_cells": int(per_label_count.sum()),
                }
            )
            print(f"EXPLORED {member}", flush=True)
    for (group, field), parts in pieces.items():
        s = pd.concat(parts).sort_index()
        expected_labels = pd.date_range(start, end, freq="h")
        assert len(s) == len(expected_labels) and (s.index == expected_labels).all()
        these = missing_runs(s)
        runs.extend({"group": group, "field": field, **r} for r in these)
        good = s.dropna()
        field_summary.append(
            {
                "group": group,
                "field": field,
                "declared_labels": len(s),
                "finite_records": len(good),
                "first_numeric_label": str(good.index.min()),
                "last_numeric_label": str(good.index.max()),
                "missing_runs": len(these),
                "longest_missing_labels": max((r["hours"] for r in these), default=0),
                "internal_runs_24h_or_more": sum(
                    r["position"] == "internal" and r["hours"] >= 24 for r in these
                ),
            }
        )
    result = {
        name: write_csv(filename, rows)
        for name, filename, rows in [
            ("yearly", "hourly_field_year.csv", yearly),
            ("cross", "qc_record_cross_table.csv", cross),
            ("monthly", "hourly_field_month.csv", monthly),
            ("contexts", "range_flag_context.csv", contexts),
            ("runs", "missing_runs.csv", runs),
            ("fields", "field_coverage_summary.csv", field_summary),
            ("outside", "outside_declared_numeric_records.csv", outside),
            ("labels", "hourly_group_label_coverage.csv", label_coverage),
        ]
    }
    result["shared_gaps"] = write_csv(
        "shared_internal_gap_intervals.csv",
        result["runs"]
        .loc[result["runs"].position.eq("internal")]
        .groupby(["group", "start_label", "end_label", "hours"])
        .field.nunique()
        .reset_index(name="fields_with_identical_gap")
        .sort_values("hours", ascending=False),
    )
    y = result["yearly"]
    metrics = [
        "calendar_labels",
        "declared_labels",
        "outside_declared_labels",
        "calendar_finite",
        "declared_finite",
        "outside_declared_finite",
        "qc0_numeric",
        "qc4_numeric",
        "range_flags_declared",
        *STATE_NAMES,
    ]
    groups = y.groupby(["group", "year"])[metrics].sum().reset_index()
    groups["calendar_missing_fraction"] = 1 - groups.calendar_finite / groups.calendar_labels
    groups["declared_missing_fraction"] = 1 - groups.declared_finite / groups.declared_labels
    mapped = y.loc[y.qc_provided].groupby(["group", "year"]).declared_labels.sum()
    groups["qc_mapped_cells"] = [int(mapped.get((r.group, r.year), 0)) for r in groups.itertuples()]
    result["groups"] = write_csv("hourly_group_year.csv", groups)
    return result


def temperature_months() -> pd.DataFrame:
    daily = pd.read_parquet(TAB / "daily_temperature_as_provided.parquet")
    result = []
    for month, frame in daily.groupby(daily.index.to_period("M")):
        for county in frame:
            result.append(
                {
                    "year": int(month.year),
                    "month": int(month.month),
                    "county": county,
                    "records": len(frame),
                    "expected_days": int(month.days_in_month),
                    "complete_month": len(frame) == month.days_in_month
                    and frame[county].notna().all(),
                    "mean_celsius": float(frame[county].mean()),
                }
            )
    return write_csv("daily_temperature_months.csv", result)


def save_fig(fig, name):
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"{name}.{suffix}", bbox_inches="tight", dpi=180)
    plt.close(fig)


def make_figures(result, temp):
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
        }
    )
    groups = result["groups"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6), layout="constrained")
    for ax, key, title in zip(
        axes,
        ["calendar_missing_fraction", "declared_missing_fraction"],
        ["全年测量单元格作分母", "官方声明窗内测量单元格作分母"],
    ):
        table = groups.pivot(index="group", columns="year", values=key) * 100
        im = ax.imshow(table, vmin=0, vmax=50, cmap="YlOrRd", aspect="auto")
        ax.set(
            xticks=range(len(table.columns)),
            xticklabels=table.columns,
            yticks=range(len(table)),
            yticklabels=table.index,
            title=title,
        )
        for i in range(len(table)):
            for j in range(len(table.columns)):
                val = table.iloc[i, j]
                ax.text(
                    j,
                    i,
                    "<0.01" if 0 < val < 0.01 else f"{val:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
    fig.colorbar(im, ax=axes, label="测量单元格缺测占比（%；未按QC筛选）", shrink=0.85)
    save_fig(fig, "coverage_denominators")

    cross = result["cross"]
    codes = ["0", "1", "2", "4", "8", "9", "qc_missing"]
    official = {
        "0": "0 正确",
        "1": "1 可疑",
        "2": "2 错误",
        "4": "4 提供方插补",
        "8": "8 缺失",
        "9": "9 未质控",
        "qc_missing": "QC本身缺失",
    }
    table = (
        cross.loc[~cross.qc.eq("not_provided")]
        .groupby(["group", "qc"])["count"]
        .sum()
        .unstack(fill_value=0)
    )
    table = table.reindex(columns=[c for c in codes if c in table], fill_value=0)
    proportions = table.div(table.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(10, 3.7), layout="constrained")
    proportions.rename(columns=official).plot.barh(
        stacked=True,
        ax=ax,
        color=["#277da8", "#f9c74f", "#f94144", "#90be6d", "#bdbdbd", "#8c6bb1", "#252525"][
            : len(proportions.columns)
        ],
    )
    ax.set(
        xlim=(0, 100),
        xlabel="已提供QC字段的单元格占比（%）",
        ylabel="",
        title="官网声明覆盖窗内QC码组成；Precip及FLUX不默认赋0",
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False, fontsize=9)
    save_fig(fig, "qc_composition")

    longest = result["shared_gaps"].head(8).iloc[::-1]
    fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
    labels = longest.apply(
        lambda r: (
            f"{r['group']}，{r['fields_with_identical_gap']}字段\n{r['start_label']} — {r['end_label']}"
        ),
        axis=1,
    )
    ax.barh(labels, longest.hours, color="#477998")
    ax.set(
        xlabel="连续缺测小时标签数（非仪器停机时长认定）",
        title="最长内部缺段：相同组别及起止标签合并展示（前8段）",
    )
    ax.bar_label(ax.containers[0], padding=3, fontsize=9)
    ax.set_xlim(0, max(longest.hours) * 1.12)
    save_fig(fig, "longest_internal_gaps")

    counties = temp.county.unique()
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), sharex=True, layout="constrained")
    for ax, county in zip(axes.flat, counties):
        base = temp.loc[
            (temp.county == county) & temp.year.between(2005, 2024) & temp.complete_month
        ]
        stats = base.groupby("month").mean_celsius.agg(["median", "min", "max"])
        current = temp.loc[(temp.county == county) & temp.year.eq(2025) & temp.complete_month]
        ax.fill_between(
            stats.index,
            stats["min"],
            stats["max"],
            color="#b7d7e8",
            alpha=0.5,
            label="2005—2024各年完整月均值范围",
        )
        ax.plot(stats.index, stats["median"], color="#2b6f95", label="2005—2024月均值中位数")
        ax.plot(
            current.month,
            current.mean_celsius,
            color="#cf5b35",
            marker="o",
            markersize=3,
            label="2025完整月份",
        )
        ax.set(title=county, xticks=[1, 4, 7, 10, 12], xlabel="月份", ylabel="气温（℃）")
        ax.grid(alpha=0.2)
    axes.flat[-1].axis("off")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[-1].legend(handles, labels, loc="center", frameon=False, fontsize=9)
    fig.suptitle("五县日温的月背景：2025年8月不完整，未混入完整月比较；阴影不是置信区间")
    save_fig(fig, "temperature_monthly_background")


def table(frame: pd.DataFrame) -> str:
    display = frame.astype(object).where(frame.notna(), "—")
    return (
        "| "
        + " | ".join(map(str, display.columns))
        + " |\n| "
        + " | ".join(["---"] * len(display.columns))
        + " |\n"
        + "\n".join(
            "| " + " | ".join(map(str, row)) + " |"
            for row in display.itertuples(index=False, name=None)
        )
    )


def build_report(result, temp, start, end, verification):
    groups = result["groups"]
    present = groups.loc[
        groups.year.isin([2021, 2026]),
        ["group", "year", "calendar_missing_fraction", "declared_missing_fraction"],
    ].copy()
    for col in ["calendar_missing_fraction", "declared_missing_fraction"]:
        present[col] = present[col].map(lambda v: "<0.01%" if 0 < v < 0.0001 else f"{v:.2%}")
    present.columns = ["组别", "年份", "全年标签缺测率", "声明窗内缺测率"]
    cross = result["cross"]
    discrepancies = cross.loc[
        (cross.qc.eq("0") & cross.record_state.ne("finite_record"))
        | (cross.qc.eq("8") & cross.record_state.eq("finite_record"))
    ]
    discrep_total = int(discrepancies["count"].sum())
    anomalies = result["contexts"].loc[result["contexts"].offset_records.eq(0)]
    alarm_table = anomalies.groupby(["group", "field", "qc"]).size().reset_index(name="条数")
    longest = result["shared_gaps"].head(5)
    qc_counts = (
        cross.loc[~cross.qc.eq("not_provided")]
        .groupby(["group", "qc"])["count"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    label_table = result["labels"].loc[
        result["labels"].year.isin([2022, 2026]),
        [
            "group",
            "year",
            "declared_hour_labels",
            "all_fields_numeric_labels",
            "partial_numeric_labels",
            "all_fields_missing_labels",
        ],
    ]
    unmapped = (
        result["yearly"].loc[~result["yearly"].qc_provided, ["group", "field"]].drop_duplicates()
    )
    outside = result["outside"]
    report = f"""# 第二阶段：无标签观测探索

生成：{datetime.now(timezone.utc).isoformat()}。输入为原始小时CSV和上阶段按原值保存的日温表。
仅做记录质量与背景描述；不生成灾害标签、累计降水、训练样本或预测评价。
F=本地可核验数值/官方定义；I=推断；U=原因或业务定义未决。官网依据见[元数据复核](metadata-review.md)。

## 1. 分母与时段（F）

官网声明观测标签覆盖{start}至{end}，为北京时间UTC+8，两端均纳入标签计数。
全年标签缺测率与声明窗内缺测率分别计算；声明窗不等于已证实的连续仪器运行期。
缺测包括解析器识别的缺失标记、额外非数值标记、9999.9、非有限值；数值记录未再按QC删除。
其中`native_missing`包括源文件字面`NaN`，额外非数值项为`NAN`，不能把解析器缺失分类说成源CSV空白单元格。
0是原值，不等于用0填补缺测。
以下百分比以“小时标签×测量字段”的单元格为分母，不是缺测小时比例或事件比例。

另发现声明窗外存在{len(outside)}个数值单元格，涉及{outside.label.nunique()}个小时标签，最早{outside.label.min()}、最晚{outside.label.max()}。
这些记录完整另存`outside_declared_numeric_records.csv`，未删除；本节声明窗统计仅因分母定义而单列它们。
F：文件与目录起点不完全一致。U：是否试运行、时间标注问题或目录起点误录尚无证据，不据此修正时间。

{table(present)}

![分母对比](../output/observation_exploration/coverage_denominators.png)

I：全年标签中的首尾空段会放大缺测比例；能说明覆盖设计的影响，不能据此定位故障或补齐观测。
U：FLUX实际中断、处理失败或质量剔除的原因仍缺少运行日志。

另按小时标签统计全部字段均有数值、部分字段有数值、全部字段缺测的标签数（未按QC筛选）：

{table(label_table)}

此处“全部字段均有数值”仅描述同一组各字段的数值齐全程度，不等于该小时所有记录质量合格，也不强制用它筛选后续样本。

## 2. QC与数值必须并列看（F）

在声明窗内，QC=0但记录非数值/缺测，或QC=8但记录仍有数值的对应记录共{discrep_total:,}个，详见完整交叉表。
该计数只是所定义两种对应情况，不代表其余非零码合格，也不自动裁决数据提供方出错。
未提供对应QC的测量字段共{len(unmapped)}个：FLUX的25列以及MET的Precip(mm)。不能给它们默认赋0。
QC=4按官方说明为提供方插补；本项目未新增插补。

![QC组成](../output/observation_exploration/qc_composition.png)

仅对已提供QC的字段，下面列出各码原始计数，便于查看图中占比较小的类别：

{table(qc_counts)}

I：只看非空数值可能高估可用于机制分析的记录量；只用非零QC一律删除也会混淆错误、插补和未质控。
U：最终各任务的QC准入政策尚未确定；本报告所有QC分组均为描述性视图。

## 3. 连续缺段与范围告警（F）

连续缺段先合并年份再计算；只记录缺测标签及位置，不用插值连成伪连续序列。
“内部”指该字段声明窗内首末数值之间，不等于仪器真实运行期。小时标签数不是已确认的观测累计时长。
下表将同组、起止标签完全一致的缺段合并，记录涉及字段数；不把一次共同缺段的多个字段重复当成独立中断。
不同合并区间仍可能互相重叠，表中行数不代表独立中断或故障次数。

{table(longest)}

![连续缺段](../output/observation_exploration/longest_internal_gaps.png)

可直接按物理范围标记的记录共{len(anomalies)}条，均保留原值和前后各2条上下文；全体分组如下。

{table(alarm_table)}

范围告警不采用IQR尾部值作为自动删除依据。相对湿度超过100%与体积含水率超过1是核查线索；原因未证实，不裁剪。
原始词元、标签、QC及邻近记录见`range_flag_context.csv`；相邻告警的上下文允许重复，不重复计作告警。

## 4. 日温背景（F）

日温仅按附件自带日期汇总，不赋未经确认的日界线，也不与小时塔站进行严格同日同点对照。
2005—2024完整月份提供各年完整月均值范围及中位数；2025只展示完整月份。
2025年8月只有2天，保留原表但排除完整月比较。阴影是跨年范围，不是95%置信区间或预报区间。

![五县月温背景](../output/observation_exploration/temperature_monthly_background.png)

I：这提供县域季节背景，不能用2025记录代表2026临灾天气，也不能把ERA5-Land再分析当作事前已发布预报。

## 5. 四问的后续工作边界

| 赛题问题 | 当前可以推进 | 仍需证据才能完成 |
| --- | --- | --- |
| 第一问关联特征 | 核对物理变量、质量码、覆盖和季节背景；按原记录探索变量关系 | 明确比较目标与独立样本单位，才能解释灾害关联和稳定排序 |
| 第二问触发评估 | 梳理冰川静态条件、历史类型与研究区覆盖 | 阈值标定需要可信发生时间与未发生记录，不能拿静态flag替代 |
| 第三问预报区间 | 记录信息可得时刻、事件阶段和验证单位的证据缺口 | 触发/到达/报告须独立确认；最终标签、降水特征和95%覆盖率结论继续暂缓 |
| 第四问仿真 | 在已有DEM覆盖范围内准备地形核验与情景参数目录 | 灾前地形状态、物源量/流量与过程记录尚未标定，不给情景贴“真实复现”标签 |

本阶段不推荐随机分层五折：尚未定义样本与目标；小时相邻记录、同次事件和同一空间单元不能自动视为独立。
模型选择留待目标和验证对象明确之后；QC/缺测情况是数据适用性信息，不是特征重要性。

## 6. 复现与输出

运行：`conda run -n mc-base --no-capture-output python scripts/explore_observations.py`。
所有新输出位于`output/observation_exploration/`；CSV为UTF-8 BOM，图含PNG/SVG。
`hourly_field_year.csv`、`hourly_group_year.csv`给出两种覆盖分母；`hourly_field_month.csv`给出原记录的分布描述。
`qc_record_cross_table.csv`保留QC×记录状态×字段×年的完整计数；`missing_runs.csv`记录全部连续缺段。
`field_coverage_summary.csv`记录各字段声明窗内首末数值标签；`daily_temperature_months.csv`明确完整月份。
`hourly_group_label_coverage.csv`按小时标签分解完整/部分/全缺测；`shared_internal_gap_intervals.csv`按相同边界合并内部缺段。
`verification.json`记录原始包校验、计数守恒与配置约束。本轮{sum(verification["checks"].values())}项数据级检查通过；这不等于科学假设或预测能力已验证。
仍待确认内容见[待确认事项清单](pending-questions.md)。
"""
    (ROOT / "docs/observation-exploration.md").write_text(report, encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = ROOT / "config/analysis-constraints.yml"
    config_hash = sha256(config_path)
    constraints = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    start, end, window_evidence = load_observation_window()
    manifest = json.loads((TAB / "archive_manifest.json").read_text(encoding="utf-8"))
    hashes = {r["archive"]: sha256(ROOT / "data/附件" / r["archive"]) for r in manifest}
    assert all(hashes[r["archive"]] == r["sha256"] for r in manifest), (
        "Raw input changed before exploration"
    )
    archive = next(ROOT / "data/附件" / r["archive"] for r in manifest if r["attachment"] == 1)
    result = audit_records(
        archive, start, end, constraints["hourly_observations"]["official_missing_value"]
    )
    temp = temperature_months()
    y = result["yearly"]
    previous = pd.read_csv(TAB / "hourly_field_quality.csv")
    joined = y.merge(
        previous[["file", "field", "diagnostic_nonmissing"]],
        on=["file", "field"],
        validate="one_to_one",
    )
    checks = {
        "all_original_archive_hashes_unchanged": all(
            sha256(ROOT / "data/附件" / r["archive"]) == r["sha256"] for r in manifest
        ),
        "calendar_numeric_counts_match_independent_prior_audit": len(joined)
        == len(previous)
        == len(y)
        and bool(joined.calendar_finite.eq(joined.diagnostic_nonmissing).all()),
        "declared_record_states_partition_all_cells": bool(
            y[STATE_NAMES].sum(axis=1).eq(y.declared_labels).all()
        ),
        "calendar_partitions_into_declared_and_outside": bool(
            y.calendar_labels.eq(y.declared_labels + y.outside_declared_labels).all()
        ),
        "qc_cross_table_accounts_for_all_declared_cells": int(result["cross"]["count"].sum())
        == int(y.declared_labels.sum()),
        "all_outside_numeric_records_preserved": int(y.outside_declared_finite.sum())
        == len(result["outside"]),
        "numeric_counts_partition_into_inside_and_outside": bool(
            y.calendar_finite.eq(y.declared_finite + y.outside_declared_finite).all()
        ),
        "63_field_series_and_378_field_years": len(result["fields"]) == 63 and len(y) == 378,
        "missing_run_labels_reconcile": int(result["runs"].hours.sum())
        == int((y.declared_labels - y.declared_finite).sum()),
        "range_flags_match_context_centers": int(y.range_flags_declared.sum())
        == int(result["contexts"].offset_records.eq(0).sum()),
        "label_categories_partition_declared_hours": bool(
            result["labels"][
                ["all_fields_numeric_labels", "all_fields_missing_labels", "partial_numeric_labels"]
            ]
            .sum(axis=1)
            .eq(result["labels"].declared_hour_labels)
            .all()
        ),
        "label_and_field_numeric_counts_reconcile": int(result["labels"].finite_cells.sum())
        == int(y.declared_finite.sum()),
        "precip_and_flux_have_no_assumed_qc": len(
            y.loc[~y.qc_provided, ["group", "field"]].drop_duplicates()
        )
        == 26,
        "config_unchanged": sha256(config_path) == config_hash,
        "final_labels_and_rain_features_still_deferred": constraints["prediction"][
            "final_time_labels"
        ]
        == "deferred"
        and constraints["precipitation"]["final_rolling_features"] == "deferred",
        "2025_august_is_partial": bool(
            (~temp.loc[temp.year.eq(2025) & temp.month.eq(8), "complete_month"]).all()
        ),
    }
    verification = {
        "passed": all(checks.values()),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "source_hashes": hashes,
        "observation_window_reference": window_evidence,
        "constraints_sha256": config_hash,
        "declared_label_window": {"start": str(start), "end": str(end), "timezone": "UTC+8"},
        "policies": {
            "raw_writes": False,
            "new_imputation": False,
            "automatic_qc_deletion": False,
            "rain_accumulation": False,
            "final_prediction_labels": False,
        },
    }
    (OUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    if not verification["passed"]:
        raise SystemExit("Exploration verification failed")
    make_figures(result, temp)
    build_report(result, temp, start, end, verification)
    print(f"Exploration complete: {OUT}", flush=True)


if __name__ == "__main__":
    main()
