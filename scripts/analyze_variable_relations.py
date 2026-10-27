"""第一问前置非降水探索；只写独立输出，不修改原包、既有产物或约束。"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from itertools import combinations
import json
from pathlib import Path
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from explore_observations import declared_window, record_states, sha256

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/variable_relations"
TAB = ROOT / "output/data_audit/tabular"
YEARS = (2022, 2023, 2024, 2025)
MIN_LABELS = 18
MIN_PAIRS = 30
VIEWS = {"qc0": {0}, "qc0_plus4": {0, 4}}
# Preselected physical examples, not a data-driven importance ranking.
SELECTED = [
    ("MET", "WS_2m(m/s)", "WS2", "近地风速", "区域近地动力背景；需全高度同步剖面后才能讨论风切变"),
    ("MET", "WS_20m(m/s)", "WS20", "近地风速", "与2m风速作同类观测关系示例，不单凭相关判稳定度"),
    ("MET", "Ta_2m(degree C)", "Ta2", "空气热力", "区域近地气温；不能替代灾区冰体温度或融化量"),
    ("MET", "Ta_20m(degree C)", "Ta20", "空气热力", "与2m气温作同类观测关系示例；日中位数之差不作瞬时梯度"),
    ("MET", "RH_2m(%)", "RH2", "空气水汽", "近地相对湿度背景；不直接代表局地凝结或降水"),
    ("MET", "Pressure(hPa)", "P", "空气热力", "站点气压背景；不能独立判定天气系统"),
    ("RADM", "Rsd(W/m2)", "Rsd", "辐射输入", "向下短波辐射背景；日中位数不等于日辐射能量"),
    ("RADM", "Rld(W/m2)", "Rld", "辐射输入", "向下长波辐射背景；不单凭相关归因云、水汽或温度"),
    ("SOIL", "soilT_0.1m(degree C)", "Ts0.1", "土壤热状态", "站点浅层土温；不替代灾区冻土/冰体温度"),
    ("SOIL", "soilT_0.8m(degree C)", "Ts0.8", "土壤热状态", "站点较深层土温背景；不由此推算融深或热传导系数"),
    ("SOIL", "VWC_0.1m(m3/m3)", "VWC0.1", "土壤水分", "站点浅层体积含水率；不替代灾区孔隙水压或含水率"),
    ("SOIL", "G_0.1m(W/m2)", "G0.1", "土壤热交换", "土壤热通量字段；正方向、标定与热储项尚需说明"),
]
EXAMPLE_PAIRS = [
    ("Ta_2m(degree C)", "Ta_20m(degree C)"),
    ("WS_2m(m/s)", "WS_20m(m/s)"),
    ("Ta_2m(degree C)", "soilT_0.1m(degree C)"),
    ("Ta_2m(degree C)", "Rld(W/m2)"),
    ("RH_2m(%)", "Rsd(W/m2)"),
    ("soilT_0.1m(degree C)", "VWC_0.1m(m3/m3)"),
]


def daily_medians(values: pd.DataFrame, quality: pd.DataFrame, allowed_qc: set[int]):
    """UTC+8原标签所属日，每字段>=18个可用数值标签才展示中位数。"""
    if not values.index.is_unique or not values.index.is_monotonic_increasing:
        raise ValueError("Daily input requires unique ordered hourly labels")
    if not values.index.equals(quality.index) or not values.columns.equals(quality.columns):
        raise ValueError("Value and QC axes must match exactly")
    if values.index.tz is not None:
        raise ValueError("Expected source Beijing wall-clock labels without silent timezone conversion")
    numeric = values.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.where(np.isfinite(numeric) & numeric.ne(9999.9))
    qc = quality.apply(pd.to_numeric, errors="coerce")
    accepted = numeric.where(qc.isin(allowed_qc))
    counts = accepted.resample("D").count()
    medians = accepted.resample("D").median().where(counts.ge(MIN_LABELS))
    return medians, counts


def within_year_month_center(daily: pd.DataFrame) -> pd.DataFrame:
    """样本内年×月中位数中心化；描述性比较，不是因果调整或事前可用特征。"""
    centers = daily.groupby([daily.index.year, daily.index.month]).transform("median")
    return daily - centers


def pairwise_spearman(daily: pd.DataFrame, view: str, transform: str) -> pd.DataFrame:
    """完整参考年内逐对完整日，秩相关平均处理并列秩，不做显著性检验。"""
    reference = daily.loc[daily.index.year.isin(YEARS)]
    scopes = [("2022-2025", reference)] + [(str(year), reference.loc[reference.index.year == year]) for year in YEARS]
    rows = []
    for period, subset in scopes:
        for a, b in combinations(daily.columns, 2):
            paired = subset[[a, b]].dropna()
            count = len(paired)
            status = "ok"
            rho = np.nan
            if count < MIN_PAIRS:
                status = "fewer_than_30_pairs"
            elif paired[a].nunique() < 2 or paired[b].nunique() < 2:
                status = "constant_series"
            else:
                # Spearman = Pearson correlation of average ranks; no p-value emitted.
                rho = paired.rank(method="average").corr(method="pearson").iloc[0, 1]
            rows.append(dict(view=view, transform=transform, period=period, field_a=a, field_b=b,
                             n_matched_days=count, spearman_rho=rho, status=status))
    return pd.DataFrame(rows)


def write_csv(name: str, frame: pd.DataFrame, index: bool = False):
    frame.to_csv(OUT / name, index=index, encoding="utf-8-sig")


def load_selected(archive: Path, dictionary: pd.DataFrame, start, end):
    """精确查字典QC列，并保留全源标签数值用于独立既有审计互校。"""
    numeric_pieces = {g: [] for g in dictionary.group.unique()}
    qc_pieces = {g: [] for g in dictionary.group.unique()}
    coverage, cross = [], []
    with ZipFile(archive) as source:
        for member in sorted(n for n in source.namelist() if n.endswith(".csv")):
            group = member.split("_")[0]
            fields = dictionary.loc[dictionary.group.eq(group)]
            if fields.empty:
                continue
            frame = pd.read_csv(BytesIO(source.read(member)))
            index = pd.DatetimeIndex(pd.to_datetime(frame.Timestamp), name="Timestamp")
            if not index.is_unique or not index.is_monotonic_increasing:
                raise ValueError(f"Duplicate or unordered raw labels: {member}")
            declared = (index >= start) & (index <= end)
            numeric_frame, quality_frame = pd.DataFrame(index=index), pd.DataFrame(index=index)
            for field in fields.itertuples(index=False):
                if field.qc_field not in frame:
                    raise ValueError(f"Dictionary QC field absent: {field.qc_field}")
                values = pd.to_numeric(frame[field.field], errors="coerce")
                finite = np.isfinite(values) & values.ne(9999.9)
                quality = pd.to_numeric(frame[field.qc_field], errors="coerce")
                numeric_frame[field.field] = values.where(finite).to_numpy()
                quality_frame[field.field] = quality.to_numpy()
                coverage.append(dict(group=group, field=field.field, year=int(index[0].year), file=member,
                    source_labels=len(index), source_numeric=int(finite.sum()),
                    declared_labels=int(declared.sum()), declared_numeric=int((finite & declared).sum()),
                    outside_declared_numeric=int((finite & ~declared).sum()),
                    declared_numeric_qc0=int((finite & declared & quality.eq(0)).sum()),
                    declared_numeric_qc4=int((finite & declared & quality.eq(4)).sum()),
                    declared_numeric_qc0_plus4=int((finite & declared & quality.isin({0, 4})).sum())))
                states = record_states(frame[field.field], 9999.9)
                qc_strings = quality.map(lambda value: "qc_missing" if pd.isna(value) else format(value, "g"))
                cells = pd.DataFrame({"qc": qc_strings.to_numpy(), "record_state": states.to_numpy()})
                for (qc_label, state), count in cells.loc[declared].value_counts().items():
                    cross.append(dict(group=group, field=field.field, year=int(index[0].year),
                                      qc=qc_label, record_state=state, count=int(count)))
            numeric_pieces[group].append(numeric_frame)
            qc_pieces[group].append(quality_frame)
    groups = {g: pd.concat(pieces).sort_index() for g, pieces in numeric_pieces.items()}
    qualities = {g: pd.concat(pieces).sort_index() for g, pieces in qc_pieces.items()}
    for group in groups:
        if not groups[group].index.is_unique:
            raise ValueError(f"Cross-file labels overlap: {group}")
    fields = dictionary.field.tolist()
    values = pd.concat(groups.values(), axis=1)[fields]
    quality = pd.concat(qualities.values(), axis=1)[fields]
    mask = (values.index >= start) & (values.index <= end)
    return values.loc[mask], quality.loc[mask], pd.DataFrame(coverage), pd.DataFrame(cross), groups


def make_plots(correlations: pd.DataFrame, dictionary: pd.DataFrame):
    fields = dictionary.field.tolist()
    names = dictionary.short_name.tolist()
    aliases = dict(zip(fields, names))
    fig, axes = plt.subplots(1, 2, figsize=(19, 8), constrained_layout=True)
    for ax, transform, title in zip(axes, ["raw_daily", "within_year_month_centered"],
                                    ["Daily median", "Within-year-month centered daily median"]):
        matrix = pd.DataFrame(np.nan, index=fields, columns=fields)
        for field in fields:
            matrix.loc[field, field] = 1.0
        subset = correlations.loc[correlations.view.eq("qc0") & correlations.period.eq("2022-2025") & correlations["transform"].eq(transform)]
        for row in subset.itertuples(index=False):
            matrix.loc[row.field_a, row.field_b] = matrix.loc[row.field_b, row.field_a] = row.spearman_rho
        artist = ax.imshow(matrix, vmin=-1, vmax=1, cmap="RdBu_r")
        ax.set_xticks(range(len(fields)), names, rotation=45, ha="right")
        ax.set_yticks(range(len(fields)), names)
        ax.set_title(title + "\nQC0, 2022-2025, Spearman rho")
        for i in range(len(fields)):
            for j in range(len(fields)):
                value = matrix.iloc[i, j]
                ax.text(j, i, "NA" if pd.isna(value) else f"{value:.2f}", ha="center", va="center",
                        fontsize=7, color="white" if abs(value) > 0.65 else "black")
    fig.colorbar(artist, ax=axes, shrink=0.75, label="Spearman rho; matched-day n in correlations.csv")
    fig.suptitle("Non-rain inter-variable description; not hazard association or causal ranking")
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"correlation_heatmaps.{suffix}", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex=True, sharey=True, constrained_layout=True)
    for ax, (a, b) in zip(axes.flat, EXAMPLE_PAIRS):
        # Pair order follows selected-field order; examples are fixed before reading results.
        subset = correlations.loc[correlations.field_a.eq(a) & correlations.field_b.eq(b) &
                                  correlations.view.eq("qc0") & ~correlations.period.eq("2022-2025")]
        for transform, label, marker in [("raw_daily", "Daily median", "o"),
                                          ("within_year_month_centered", "Year-month centered", "s")]:
            part = subset.loc[subset["transform"].eq(transform)].sort_values("period")
            ax.plot(part.period.astype(int), part.spearman_rho, marker=marker, label=label)
            if transform == "raw_daily":
                for row in part.itertuples(index=False):
                    ax.annotate(f"n={row.n_matched_days}", (int(row.period), row.spearman_rho),
                                xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7)
        ax.set_title(f"{aliases[a]} vs {aliases[b]}")
        ax.axhline(0, color="gray", lw=0.7)
        ax.set_ylim(-1.08, 1.12)
        ax.set_xticks(YEARS)
        ax.grid(alpha=0.2)
    axes[0, 0].legend(fontsize=8, loc="lower left")
    fig.supylabel("Spearman rho")
    fig.suptitle("QC0 yearly variability: six preselected examples, not importance ranking\nAnnotations are matched-day n; no independent-sample or significance claim")
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"year_variability.{suffix}", dpi=160)
    plt.close(fig)


def build_report(dictionary, coverage, daily_coverage, correlations, sensitivity, verification):
    field_rows = "\n".join(f"| {r.group} | `{r.field}` | `{r.qc_field}` | {r.physical_group} | {r.physical_interpretation_I} |" for r in dictionary.itertuples(index=False))
    example_rows = []
    for a, b in EXAMPLE_PAIRS:
        example = correlations.loc[correlations.field_a.eq(a) & correlations.field_b.eq(b) & correlations.view.eq("qc0")]
        raw = example.loc[example.period.eq("2022-2025") & example["transform"].eq("raw_daily")].iloc[0]
        centered = example.loc[example.period.eq("2022-2025") & example["transform"].eq("within_year_month_centered")].iloc[0]
        years = example.loc[~example.period.eq("2022-2025") & example["transform"].eq("raw_daily")]
        example_rows.append(f"| `{a}` / `{b}` | {raw.n_matched_days} | {raw.spearman_rho:.3f} | {centered.spearman_rho:.3f} | {years.spearman_rho.min():.3f}～{years.spearman_rho.max():.3f} |")
    ref_coverage = daily_coverage.loc[daily_coverage.year.isin(YEARS) & daily_coverage.view.eq("qc0")]
    changed = sensitivity.loc[sensitivity["transform"].eq("raw_daily") & sensitivity.period.eq("2022-2025")]
    source_reference = coverage.loc[coverage.year.isin(YEARS)]
    min_days, max_days = int(ref_coverage.groupby("field").available_daily_medians.sum().min()), int(ref_coverage.groupby("field").available_daily_medians.sum().max())
    max_delta = changed.delta_rho.abs().max()
    report = f'''# 第一问前置探索：变量物理分组与非降水关系

生成：{verification["checked_at_utc"]}。本报告是第一问的前置子步骤，尚未完成大气边界层结构、极端天气过程或泥石流关联分析，不给出最终“前5因素”。
F=本地原记录/表头或已保存官方定义可核验；I=按字段名作的物理解释或样本内解释；U=尚无足够证据。

## 1. 变量与证据地图

下表精确表头、QC列与单位来自既有`field_dictionary.csv`，属F；物理分组及用途均为I，不是已验证的机制。
选择12个字段用于有限示例，覆盖MET/RADM/SOIL，未按相关强弱、事件窗口或重要性筛选。

| 数据组 | 原字段（单位见表头） | 精确QC列（F） | 物理分组（I） | 解释边界（I） |
| --- | --- | --- | --- | --- |
{field_rows}

站点只作区域背景。官网称距受灾口岸约65km且纬度中英文冲突，不能把塔站数值代作灾害源区局地条件。已存官方证据见[元数据复核](metadata-review.md)。
降水完全不进入本轮关系分析：累计/时段语义未明，无累计、滚动、强度或衍生降水指标。
FLUX没有对应QC列，故不进入本轮主QC控制相关视图，不能默认QC=0；仍保留在第一问证据链中。
后续可补做FLUX原记录、缺段、量纲和范围检查，并与有QC的组并列呈现；在坐标方向、处理/通量符号与质量证据不全时不能直接等同可用通量或永久弃用。
风向是圆周量，本轮未对角度用普通中位数和秩相关；更全的风场分析需另定圆周统计方案。

## 2. 日描述视图（F：方法与计数）

北京时间UTC+8为已确认标签时区；统计支持区间起止仍U。按原标签所属公历日归组，不平移标签或假定小时起点/终点。
仅在每字段每日有至少18个符合该视图QC的有限数值标签时输出日中位数，其余保留为缺失；18是本轮透明展示门槛，不是官方完备性标准。
保留0原值；排除数值解析失败、9999.9、无穷值。QC0与QC0+4分别从相同源记录独立生成；QC4为提供方插补，扩展视图仅作敏感性比较，不是最终QC准入政策。
本项目不新增插补，不改/删源记录，不把日中位数当作官方日均或日能量。每日有效数值标签数另表保存。
整个声明窗内的日视图包含2021、2026首尾部分日期；相关比较只取2022—2025四个完整参考年，共1461个日历日，避免首尾部分年混入。
“完整参考年”只指日历覆盖设计，并非所有字段每天均完整。

12字段在2022—2025共有{int(source_reference.declared_labels.sum()):,}个源标签×字段单元格，其中有限数值{int(source_reference.declared_numeric.sum()):,}个、QC0有限数值{int(source_reference.declared_numeric_qc0.sum()):,}个、QC4有限数值{int(source_reference.declared_numeric_qc4.sum()):,}个。
QC0视图每字段可展示日数范围为{min_days}～{max_days}/1461；详细字段×年计数见`daily_coverage.csv`，原QC×记录状态计数见`qc_coverage.csv`。

## 3. 配对关系（F：本样本统计量；I：解读）

逐对使用共同非缺失日，分别输出总体与各年Spearman相关和配对日数n；并列秩取平均秩。n<30时系数留缺并标状态，常数列也留缺，不强置0。
n是共同日标签数，不是独立样本量。日序列具有时间依赖，故不输出p值、独立样本显著性、置信区间或灾害因果排序。

另将每字段日中位数减去其同年同月的样本中位数，观察共同季节变化可能产生的影响。
这是依赖整月样本的描述比较，不是因果调整、正式去季节化或可无泄漏用于预测的特征；未去除月内天气、趋势或跨日依赖。

以下六对在读取结果前已按物理解释选定，非相关排名：

| 字段对 | 总体n | 原日中位数ρ | 年×月中心化ρ | 原日值逐年ρ范围 |
| --- | --- | --- | --- | --- |
{chr(10).join(example_rows)}

I：同类不同高度气温、风速的相关描述观测共变；不能直接得出边界层稳定度或机械湍流强度。
I：原日值与年×月中心化值的ρ差异可提示共同季节背景与样本定义的重要性；不能把差异全部解释为季节因果贡献。
I：逐年差异提示本样本关系的时间变化；不能把强相关称为灾害驱动、预测有效、冗余可删或独立信息已证实。
QC0+4敏感性视图中，总体原日值66对的最大|Δρ|为{max_delta:.6f}；相同与否均不裁决最终QC政策。两视图的n和ρ逐对并列在`sensitivity_comparison.csv`。

![非降水相关热图](../output/variable_relations/correlation_heatmaps.png)

![六对预选变量逐年变化](../output/variable_relations/year_variability.png)

## 4. 第一问仍需的证据与下一小步（U）

| 第一问证据环节 | 已有F/I | 尚需确认或分析（U） |
| --- | --- | --- |
| 大气边界层结构 | MET多高度风、温、湿表头；本轮仅两高度背景共变 | 以同时刻成对有效标签计算全1/2/4/10/20m剖面和梯度，保留每对QC、覆盖和昼夜结构；不能用分别日中位数之差代瞬时梯度；压力高度、稳定度近似与仪器暴露需说明 |
| 地气能量与水分交换 | RADM与SOIL字段；FLUX通量与湍流候选字段 | 核实辐射/土壤/湍流通量正方向与处理；补做FLUX原记录检查和共同有效时段；能量闭合/稳定度需要合理量纲、同步与独立质量证据 |
| 天气与极端过程 | 北京时间标签与非降水分布背景 | 先定义过程单位、背景分位与季节参照，并核对时间区间；相关矩阵不能识别具体天气系统或极端过程 |
| 泥石流关联与前5因素 | 题面案例字面时刻，历史空间清单 | 可信事件/对照定义、阶段/时区/精度、源区与塔站代表性、足够独立事件；目前不能用静态flag或案例描述时刻生成最终标签与排名 |

## 5. 复现与核验

运行：`D:/miniforge3/Scripts/conda.exe run -n mc-base --no-capture-output python scripts/analyze_variable_relations.py`。
合成边界测试：同环境运行`python -m unittest discover -s tests -p test_variable_relations.py -v`。
产物仅写`output/variable_relations/`与本报告；CSV使用UTF-8 BOM。

- `selected_fields.csv`：精确表头、QC、单位/高度深度、I类物理分组与解释。
- `source_coverage.csv`、`qc_coverage.csv`：字段×年声明窗覆盖和QC×原记录状态计数，另列声明窗外数值计数而不删原记录。
- `daily_medians_qc0.csv`、`daily_medians_qc0_plus4.csv`与同名`daily_counts_*`：按标签日的两视图和有效数值计数；缺日不填。
- `daily_coverage.csv`：各视图字段×年日门槛/有效标签总数；`daily_centered_*`：样本内中心化的2022—2025比较值。
- `correlations.csv`：两视图×两变换×五时段×66字段对，共1320行，均有n和状态；`sensitivity_comparison.csv`并列QC视图。
- `verification.json`：8个原包前后SHA-256、约束文件不变、12字段全源数值逐格对照既有审计、日门槛与独立配对n等核验。{sum(verification["checks"].values())}项检查均通过，不等于科学假设、灾害关联或预测性能验证。

## 执行记录

- [x] 按writing-plans在本文件记录计划；TDD先写8个合成边界测试并观察因缺实现而失败，再实现并复验；另增图像真实渲染回归测试，复现并修正pandas只读数组与同名方法列访问问题，共9项新测试。
- [x] 只在授权新文件与输出范围写入；未提交、切换分支或调整Git状态，未修改原包或约束；未新增依赖、插补、降水特征或灾害标签。
- [x] 完成12字段两独立描述视图、逐对n、逐年/总体相关、中心化敏感性与图。
- [x] 按verification-before-completion核验原包/配置和数值保真；最终测试输出由执行者另行报告。
'''
    (ROOT / "docs/variable-relations.md").write_text(report, encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = ROOT / "config/analysis-constraints.yml"
    constraints_hash = sha256(config_path)
    constraints = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if constraints["hourly_observations"]["official_missing_value"] != 9999.9:
        raise ValueError("Official missing-code constraint changed; review aggregation first")
    manifest = json.loads((TAB / "archive_manifest.json").read_text(encoding="utf-8"))
    hashes_before = {r["archive"]: sha256(ROOT / "data/附件" / r["archive"]) for r in manifest}
    if not all(hashes_before[r["archive"]] == r["sha256"] for r in manifest):
        raise ValueError("Original archive hash mismatch before analysis")
    selected = pd.DataFrame(SELECTED, columns=["group", "field", "short_name", "physical_group", "physical_interpretation_I"])
    source_dictionary = pd.read_csv(TAB / "field_dictionary.csv")
    dictionary = selected.merge(source_dictionary, on=["group", "field"], how="left", validate="one_to_one")
    if dictionary.qc_field.isna().any() or not dictionary.role.eq("measurement").all():
        raise ValueError("Selected fields require exact provided QC mapping")
    official = ROOT / "output/metadata_review/official_pages/attachment_1_metadata_export.json"
    detail_path = official.with_name("attachment_1_standard_detail.json")
    metadata = json.loads(official.read_text(encoding="utf-8-sig"))
    detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))["context"]["metadataVO"]
    start, end = declared_window(detail, metadata)
    archive = next(ROOT / "data/附件" / r["archive"] for r in manifest if r["attachment"] == 1)
    values, quality, coverage, cross, groups = load_selected(archive, dictionary, start, end)
    source_fidelity = {}
    for group, raw_numeric in groups.items():
        prior = pd.read_parquet(TAB / f"{group.lower()}_diagnostic.parquet")[raw_numeric.columns]
        source_fidelity[group] = bool(prior.index.equals(raw_numeric.index) and
            np.array_equal(prior.to_numpy(), raw_numeric.to_numpy(), equal_nan=True))
    daily_views, daily_counts, centered_views, summaries, correlations = {}, {}, {}, [], []
    for view, qc_set in VIEWS.items():
        daily, counts = daily_medians(values, quality, qc_set)
        daily_views[view], daily_counts[view] = daily, counts
        reference = daily.loc[daily.index.year.isin(YEARS)]
        centered = within_year_month_center(reference)
        centered_views[view] = centered
        for transform, frame in [("raw_daily", daily), ("within_year_month_centered", centered)]:
            correlations.append(pairwise_spearman(frame, view, transform))
        for year in sorted(set(daily.index.year)):
            for field in daily:
                part, count = daily.loc[daily.index.year == year, field], counts.loc[counts.index.year == year, field]
                summaries.append(dict(view=view, year=year, field=field, calendar_day_labels=len(part),
                    available_daily_medians=int(part.notna().sum()), unavailable_daily_medians=int(part.isna().sum()),
                    numeric_accepted_hour_labels=int(count.sum()), minimum_labels_for_median=MIN_LABELS))
    corr = pd.concat(correlations, ignore_index=True)
    daily_coverage = pd.DataFrame(summaries)
    merge_keys = ["transform", "period", "field_a", "field_b"]
    sensitivity = corr.loc[corr.view.eq("qc0")].drop(columns="view").merge(
        corr.loc[corr.view.eq("qc0_plus4")].drop(columns="view"), on=merge_keys,
        suffixes=("_qc0", "_qc0_plus4"), validate="one_to_one")
    sensitivity["delta_rho"] = sensitivity.spearman_rho_qc0_plus4 - sensitivity.spearman_rho_qc0
    sensitivity["delta_matched_days"] = sensitivity.n_matched_days_qc0_plus4 - sensitivity.n_matched_days_qc0
    independent_n, coefficient_check = [], []
    for row in corr.itertuples(index=False):
        daily = daily_views[row.view] if row.transform == "raw_daily" else centered_views[row.view]
        selected_days = daily.loc[daily.index.year.isin(YEARS)] if row.period == "2022-2025" else daily.loc[daily.index.year == int(row.period)]
        a, b = selected_days[row.field_a], selected_days[row.field_b]
        valid = a.notna() & b.notna()
        independent_n.append(int(valid.sum()) == row.n_matched_days)
        if row.status == "ok":
            # Independent library implementation versus average-rank Pearson calculation.
            expected = a.loc[valid].corr(b.loc[valid], method="spearman")
            coefficient_check.append(bool(np.isclose(row.spearman_rho, expected, atol=1e-12)))
    checks = {
        "all_8_original_archive_hashes_match_manifest_before_and_after": all(
            hashes_before[r["archive"]] == r["sha256"] == sha256(ROOT / "data/附件" / r["archive"]) for r in manifest),
        "constraints_file_unchanged": sha256(config_path) == constraints_hash,
        "12_nonrain_fields_have_exact_provided_qc": len(dictionary) == 12 and dictionary.qc_field.notna().all() and
            set(dictionary.group) == {"MET", "RADM", "SOIL"} and not dictionary.field.str.contains("precip|rain", case=False).any(),
        "all_source_numeric_values_exactly_match_existing_independent_audit": all(source_fidelity.values()),
        "declared_qc_cross_counts_reconcile": int(cross["count"].sum()) == int(coverage.declared_labels.sum()),
        "source_numeric_counts_partition_inside_outside": bool(coverage.source_numeric.eq(coverage.declared_numeric + coverage.outside_declared_numeric).all()),
        "source_full_hour_labels_are_52584_for_each_field": all(len(group) == 52584 for group in groups.values()),
        "qc0_and_qc0_plus4_views_independent_and_counts_nested": bool((daily_counts["qc0"] <= daily_counts["qc0_plus4"]).all().all()),
        "each_daily_median_exists_iff_18_accepted_numeric_labels": all(
            daily_views[view].notna().equals(daily_counts[view].ge(MIN_LABELS)) for view in VIEWS),
        "daily_counts_equal_selected_hourly_acceptance": all(int(daily_counts[view].sum().sum()) ==
            int((values.notna() & quality.isin(qc_set)).sum().sum()) for view, qc_set in VIEWS.items()),
        "reference_calendar_has_1461_days": all(len(daily.loc[daily.index.year.isin(YEARS)]) == 1461 for daily in daily_views.values()),
        "1320_unique_pair_view_transform_period_rows": len(corr) == 1320 and not corr.duplicated(["view"] + merge_keys).any(),
        "all_pairwise_n_match_independent_boolean_overlap": all(independent_n),
        "all_available_coefficients_match_independent_scipy_spearman": all(coefficient_check),
        "unavailable_pairwise_coefficients_remain_missing": bool(corr.loc[~corr.status.eq("ok"), "spearman_rho"].isna().all()),
        "final_labels_rain_features_and_imputation_remain_deferred_or_forbidden": constraints["prediction"]["final_time_labels"] == "deferred" and
            not constraints["prediction"]["automatic_stage_time_equivalence"] and constraints["precipitation"]["final_rolling_features"] == "deferred" and
            not constraints["raw_inputs"]["new_imputation_allowed"],
    }
    checks = {key: bool(value) for key, value in checks.items()}
    verification = dict(passed=all(checks.values()), checked_at_utc=datetime.now(timezone.utc).isoformat(), checks=checks,
        source_hashes=hashes_before, constraints_sha256=constraints_hash, source_numeric_fidelity_by_group=source_fidelity,
        dictionary_sha256=sha256(TAB / "field_dictionary.csv"), official_metadata_sha256=sha256(official),
        official_detail_sha256=sha256(detail_path),
        declared_label_window={"start": str(start), "end": str(end), "timezone": "UTC+8", "support_interval": None},
        method={"min_numeric_hour_labels_per_day": MIN_LABELS, "min_paired_day_labels": MIN_PAIRS,
                "reference_years": list(YEARS), "views": {key: sorted(value) for key, value in VIEWS.items()},
                "new_imputation": False, "precipitation_features": False, "hazard_labels": False,
                "p_values": False, "physical_interpretation_evidence": "I: name-based"})
    (OUT / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {key}", flush=True)
    if not verification["passed"]:
        raise SystemExit("Variable-relation verification failed")
    for name, frame in [("selected_fields.csv", dictionary), ("source_coverage.csv", coverage), ("qc_coverage.csv", cross),
                         ("daily_coverage.csv", daily_coverage), ("correlations.csv", corr), ("sensitivity_comparison.csv", sensitivity)]:
        write_csv(name, frame)
    for view in VIEWS:
        for prefix, frame in [("daily_medians", daily_views[view]), ("daily_counts", daily_counts[view]), ("daily_centered", centered_views[view])]:
            frame.index.name = "label_calendar_date_BeijingUTC8"
            write_csv(f"{prefix}_{view}.csv", frame, index=True)
    make_plots(corr, dictionary)
    build_report(dictionary, coverage, daily_coverage, corr, sensitivity, verification)
    print(f"Variable relation description complete: {OUT}", flush=True)


if __name__ == "__main__":
    main()
