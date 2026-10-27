"""First-question case contrast, fixed before inspecting the case results.

Read the original hourly archive once; no fitting, filling, rain accumulation,
negative event labels, causal estimates, or new interpretation of source QC.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from zipfile import ZipFile, ZIP_DEFLATED

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from project_runtime import PROJECT_ROOT as ROOT, sha256_file, verify_input_files

OUT = ROOT / "output/question1"
# Order is the deterministic tie-break, chosen before looking at event effects.
# Family selection prevents two near-duplicate heights taking multiple top places.
FEATURES = [
    ("Ta2", "近地气温与热力结构", "2米气温", "℃", "区域热背景，不等于冰体温度或实际融水量"),
    ("TaG", "近地气温与热力结构", "2—20米气温梯度", "℃/m", "同时刻温差/18m，不单独判定静力稳定度"),
    ("RH2", "空气湿度结构", "2米相对湿度", "%", "区域相对湿度背景，不等于灾区凝结或降水"),
    ("RHG", "空气湿度结构", "2—20米湿度梯度", "百分点/m", "相对湿度的垂直差异，不是绝对水汽梯度"),
    ("WS2", "近地风速结构", "2米风速", "m/s", "区域近地动力背景，不等于冰崩机械触发力"),
    (
        "WSG",
        "近地风速结构",
        "2—20米标量风速梯度",
        "(m/s)/m",
        "标量速度差/18m，不是矢量风切变或Richardson数",
    ),
    ("P", "气压背景", "站点气压", "hPa", "气压过程背景，不能单独判断天气系统或作因果归因"),
    ("Rsd", "辐射收支背景", "向下短波辐射", "W/m²", "辐射输入背景，不将中位数称为累计能量"),
    ("Rld", "辐射收支背景", "向下长波辐射", "W/m²", "区域下行长波背景，不能仅由此判断云量或融化"),
    ("Rn", "辐射收支背景", "四分量净辐射", "W/m²", "下行减上行的同步辐射收支，不含其他能量项"),
    ("Ts", "土壤热状态", "0.1米土壤温度", "℃", "塔站浅层土壤热背景，不等于源区冰体或冻土温度"),
    (
        "TsG",
        "土壤热状态",
        "0.1—0.8米土温深度梯度",
        "℃/m",
        "沿深度增加方向的同步温差/0.7m，不直接给出热传导通量",
    ),
    (
        "VWC",
        "土壤水分背景",
        "0.1米土壤体积含水率",
        "m³/m³",
        "站点土壤湿润背景，不等于源区孔隙水压或含水率",
    ),
]


def last_label(onset: str, guard_hours: int) -> pd.Timestamp:
    """A conservative LABEL cutoff; unknown averaging support is not resolved."""
    t = pd.Timestamp(onset)
    if t.tz is None:
        raise ValueError("Explicit event timezone required")
    if guard_hours < 1:
        raise ValueError("At least one excluded clock-hour label is required")
    return t.tz_convert("Asia/Shanghai").tz_localize(None).floor("h") - pd.Timedelta(
        hours=guard_hours
    )


def reference_anchors(anchor: pd.Timestamp, years: list[int], half_width: int):
    if any(y >= anchor.year for y in years) or len(years) != len(set(years)):
        raise ValueError("Unique strictly earlier reference years required")
    return [
        anchor.replace(year=y) + pd.Timedelta(days=d)
        for y in years
        for d in range(-half_width, half_width + 1)
    ]


def window_summary(series, anchor, hours, minimum_coverage):
    if not series.index.is_unique or not series.index.is_monotonic_increasing:
        raise ValueError("Unique ordered source labels required")
    labels = pd.date_range(end=anchor, periods=hours, freq="h")
    values = pd.to_numeric(series.reindex(labels), errors="coerce")
    values = values.where(np.isfinite(values))
    n = int(values.notna().sum())
    return (float(values.median()) if n >= math.ceil(hours * minimum_coverage) else np.nan), n


def contrast(case, reference, minimum_n):
    r = np.asarray(reference, dtype=float)
    r = r[np.isfinite(r)]
    result = dict(
        reference_n=len(r),
        reference_median=np.nan,
        reference_q05=np.nan,
        reference_q95=np.nan,
        percentile=np.nan,
        D=np.nan,
        robust_z=np.nan,
    )
    if len(r):
        median = float(np.median(r))
        result.update(
            reference_median=median,
            reference_q05=float(np.quantile(r, 0.05)),
            reference_q95=float(np.quantile(r, 0.95)),
        )
    if len(r) < minimum_n or not np.isfinite(case):
        return result
    # Midrank ties: p=P(reference<case)+0.5 P(reference=case).
    p = float(((r < case).sum() + 0.5 * (r == case).sum()) / len(r))
    mad = float(np.median(np.abs(r - median)))
    result.update(
        percentile=100 * p,
        D=2 * p - 1,
        robust_z=(case - median) / (1.4826 * mad) if mad > 0 else np.nan,
    )
    return result


def pair_difference(upper, lower, spacing):
    if not upper.index.equals(lower.index) or spacing <= 0:
        raise ValueError("Matching labels and positive physical spacing required")
    return (upper - lower) / spacing


def net_radiation(rsd, rsu, rld, rlu):
    if not all(s.index.equals(rsd.index) for s in [rsu, rld, rlu]):
        raise ValueError("Radiation components must have the same source labels")
    return rsd - rsu + rld - rlu


def select_families(table):
    t = table.loc[table.D.notna()].copy()
    t["abs_D"] = t.D.abs()
    return (
        t.sort_values(["abs_D", "order"], ascending=[False, True], kind="stable")
        .drop_duplicates("family")
        .head(5)
        .reset_index(drop=True)
    )


def load_raw():
    manifest = json.loads((ROOT / "config/input-manifest.json").read_text(encoding="utf-8"))
    archive = ROOT / next(x["path"] for x in manifest["archives"] if x["attachment"] == 1)
    groups = {}
    with ZipFile(archive) as source:
        for member in sorted(n for n in source.namelist() if n.endswith(".csv")):
            group = member.split("_")[0]
            f = pd.read_csv(BytesIO(source.read(member)))
            f.index = pd.DatetimeIndex(pd.to_datetime(f.pop("Timestamp")), name="Timestamp")
            if not f.index.is_unique or not f.index.is_monotonic_increasing:
                raise ValueError("Duplicate/unordered labels: " + member)
            groups.setdefault(group, []).append(f)
    result = {g: pd.concat(parts).sort_index() for g, parts in groups.items()}
    for g, f in result.items():
        if not f.index.is_unique:
            raise ValueError("Overlapping years in " + g)
    return result


def clean_field(frame, field, allowed_qc):
    s = pd.to_numeric(frame[field], errors="coerce")
    s = s.where(np.isfinite(s) & s.ne(9999.9))
    # Actual RADM headers mix QC_Rsd / QC_rsu / QC_rld / QC_rlu.
    # Match the source name case-insensitively and reject ambiguous mappings.
    expected = ("QC_" + field.split("(")[0]).lower()
    matches = [name for name in frame.columns if name.lower() == expected]
    if allowed_qc is not None:
        if len(matches) != 1:
            raise ValueError("Required source QC absent: " + field)
        qc = matches[0]
        s = s.where(pd.to_numeric(frame[qc], errors="coerce").isin(allowed_qc))
    return s


def features_from_raw(raw, allowed):
    def met(name):
        return clean_field(raw["MET"], name, allowed)

    def rad(name):
        return clean_field(raw["RADM"], name + "(W/m2)", allowed)

    def soil(name):
        return clean_field(raw["SOIL"], name, allowed)

    ta, rh, ws = met("Ta_2m(degree C)"), met("RH_2m(%)"), met("WS_2m(m/s)")
    ts = soil("soilT_0.1m(degree C)")
    return pd.DataFrame(
        {
            "Ta2": ta,
            "TaG": pair_difference(met("Ta_20m(degree C)"), ta, 18),
            "RH2": rh,
            "RHG": pair_difference(met("RH_20m(%)"), rh, 18),
            "WS2": ws,
            "WSG": pair_difference(met("WS_20m(m/s)"), ws, 18),
            "P": met("Pressure(hPa)"),
            "Rsd": rad("Rsd"),
            "Rld": rad("Rld"),
            "Rn": net_radiation(rad("Rsd"), rad("Rsu"), rad("Rld"), rad("Rlu")),
            "Ts": ts,
            "TsG": pair_difference(soil("soilT_0.8m(degree C)"), ts, 0.7),
            "VWC": soil("VWC_0.1m(m3/m3)"),
        }
    )


def compute_tables(views, anchor, config):
    anchors = reference_anchors(
        anchor, config["reference_years"], config["reference_calendar_half_width_days"]
    )
    rows, windows = [], []
    for view, features in views.items():
        for hours in config["window_hours"]:
            for order, (key, family, name, unit, meaning) in enumerate(FEATURES):
                s = features[key]
                event, event_n = window_summary(s, anchor, hours, config["minimum_window_coverage"])
                refs, ref_years = [], []
                for a in anchors:
                    m, n = window_summary(s, a, hours, config["minimum_window_coverage"])
                    refs.append(m)
                    ref_years.append(a.year)
                    windows.append(
                        dict(
                            view=view,
                            hours=hours,
                            feature=key,
                            anchor=a,
                            year=a.year,
                            valid_labels=n,
                            median=m,
                        )
                    )
                refs, ref_years = np.asarray(refs), np.asarray(ref_years)
                omissions = [None] + (
                    config["reference_years"]
                    if view == "qc0" and hours == config["primary_window_hours"]
                    else []
                )
                for omitted in omissions:
                    subset = refs if omitted is None else refs[ref_years != omitted]
                    rows.append(
                        dict(
                            view=view,
                            hours=hours,
                            omitted_year=omitted,
                            feature=key,
                            family=family,
                            name=name,
                            unit=unit,
                            order=order,
                            event_median=event,
                            event_valid_labels=event_n,
                            interpretation=meaning,
                            **contrast(event, subset, config["minimum_reference_windows"]),
                        )
                    )
    return pd.DataFrame(rows), pd.DataFrame(windows)


def hourly_bands(features, config):
    # Same season AND clock hour. Not independent events and not a hazard classifier.
    mask = pd.Series(False, index=features.index)
    for year in config["reference_years"]:
        center = pd.Timestamp(year=year, month=8, day=26)
        width = pd.Timedelta(days=config["reference_calendar_half_width_days"])
        mask |= (features.index >= center - width) & (
            features.index < center + width + pd.Timedelta(days=1)
        )
    refs = features.loc[mask]
    rows = []
    for key, _, _, _, _ in FEATURES:
        for hour in range(24):
            s = refs.loc[refs.index.hour == hour, key].dropna()
            eligible = len(s) >= config["minimum_reference_windows"]
            rows.append(
                dict(
                    feature=key,
                    hour=hour,
                    n=len(s),
                    q05=s.quantile(0.05) if eligible else np.nan,
                    median=s.median() if eligible else np.nan,
                    q95=s.quantile(0.95) if eligible else np.nan,
                )
            )
    return pd.DataFrame(rows)


def save_csv(name, table):
    table.to_csv(OUT / name, index=False, encoding="utf-8-sig", float_format="%.12g")


def figures(primary, top, case, bands, sensitivity, onset):
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
            "svg.fonttype": "none",
        }
    )
    family = (
        primary.assign(abs_D=primary.D.abs())
        .sort_values(["abs_D", "order"], ascending=[False, True])
        .drop_duplicates("family")
    )
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    ax.barh(
        family.name,
        family.D,
        color=["#177e89" if k in set(top.feature) else "#b9bfc3" for k in family.feature],
    )
    ax.invert_yaxis()
    ax.axvline(0, color="gray", lw=0.8)
    ax.set_xlim(-1.12, 1.12)
    for i, r in enumerate(family.itertuples()):
        ax.text(
            r.D + (0.02 if r.D >= 0 else -0.02),
            i,
            f"{r.D:+.3f}",
            ha="left" if r.D >= 0 else "right",
            va="center",
        )
    ax.set_xlabel("经验秩对比 D = 2p−1；排序取 |D|，不是致灾概率或因果效应")
    ax.set_title(
        "72小时标签窗：各物理类别代表指标与同期背景对比\n主口径QC0；彩色为前五类别；参照窗重叠"
    )
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"factor_contrast.{suffix}", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(5, 1, figsize=(12, 11), sharex=True, constrained_layout=True)
    for ax, r in zip(axes, top.itertuples()):
        b = bands.loc[bands.feature.eq(r.feature)].set_index("hour").reindex(case.index.hour)
        ax.fill_between(
            case.index,
            b.q05.to_numpy(),
            b.q95.to_numpy(),
            color="#dce9ee",
            label="历年同期同钟点5%—95%分位",
        )
        ax.plot(case.index, b["median"].to_numpy(), color="#718b94", ls="--", label="同期中位数")
        ax.plot(case.index, case[r.feature], color="#c85236", lw=1.2, label="案例前原小时标签")
        ax.set_ylabel(r.name + "\n" + r.unit)
        ax.grid(alpha=0.2)
        ax.axvline(onset, color="black", ls=":", lw=0.8)
    axes[0].legend(loc="upper left", fontsize=8, ncol=3)
    axes[-1].set_xlabel(
        "北京时间标签；虚线为用户报告冰崩起始10:52；曲线最晚09:00，小时支持区间仍未知"
    )
    fig.suptitle("区域背景过程：塔站距口岸约65 km，曲线不等于源区局地观测")
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"case_process.{suffix}", dpi=160)
    plt.close(fig)
    pivot = sensitivity.pivot(index="family", columns="scenario", values="family_rank").reindex(
        top.family
    )
    fig, ax = plt.subplots(figsize=(13, 4.5), constrained_layout=True)
    im = ax.imshow(pivot.to_numpy(), cmap="YlGnBu", vmin=1, vmax=7, aspect="auto")
    ax.set_yticks(range(len(pivot)), pivot.index)
    ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=35, ha="right")
    for i in range(len(pivot)):
        for j in range(len(pivot.columns)):
            v = pivot.iloc[i, j]
            ax.text(
                j,
                i,
                "NA" if pd.isna(v) else str(int(v)),
                ha="center",
                va="center",
                color="white" if v > 4 else "black",
            )
    fig.colorbar(im, ax=ax, label="类别名次，1为|D|最大")
    ax.set_title("前五类别的窗口、QC与留一历史年敏感性；非独立验证或显著性检验")
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / f"rank_sensitivity.{suffix}", dpi=160)
    plt.close(fig)


def make_report(top, all_scores, tails, flux, anchor, context, config, verification):
    lines = [
        "# 第一问首版：区域大气背景与案例关联分析",
        "",
        "状态：本轮计算与支撑交付已完成；这是单案例、区域背景口径的首版。并未建立可泛化的灾害统计因果排名，也未完成局地触发机制验证。",
        "",
        "## 可直接交给论文队友的结论",
        "",
        "我们把长期站点观测、同刻垂直结构与案例前过程结合，在季节和钟点匹配的历史参照中，筛选五个不同物理类别的异常背景因素。排名依据是案例前窗相对参照窗的经验秩差异，不能解释为灾害发生概率、因果效应或独立灾害样本相关系数。",
        "",
        "| 排名 | 因素类别 / 代表指标 | 案例中位数 | 同期参照中位数 | 经验百分位 | D | 单位 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(top.itertuples(), 1):
        lines.append(
            f"| {i} | {r.family} / {r.name} | {r.event_median:.5g} | {r.reference_median:.5g} | {r.percentile:.2f}% | {r.D:+.3f} | {r.unit} |"
        )
    lines += [
        "",
        "这里的‘前五’是已定义候选集合中的**案例背景对照前五类别**。没有事件目录及局地观测时，无法诚实证明它们就是普适意义上‘与泥石流关联最高’的五个因素；论文应保留这一限定，不把互相关或该排序改写为灾害因果重要性。",
        "",
    ]
    for i, r in enumerate(top.itertuples(), 1):
        lines.append(
            f"{i}. **{r.family}**：代表指标为{r.name}，案例值{'高于' if r.D > 0 else '低于' if r.D < 0 else '位于'}参照中位背景。{r.interpretation}。方向不自动对应风险增加或降低；季节、站点和物理尺度均有约束。"
        )
    lines += [
        "",
        "## 时间、影像与证据等级",
        "",
        "- 用户报告：2026-08-26北京时间10:52冰崩起始、10:59到达口岸；分钟精度，序列化的00秒不是秒级实测。日期沿用赛题，原始来源尚未独立核验。",
        "- 推断/条件约束：假定同一灾害链中触发不早于冰崩且不晚于到达，则触发时间属于[10:52,10:59]；不是精确标签，不赋均匀分布，不称95%置信区间。",
        "- 冲突：赛题原10:30保留，与本轮时间线不一致，尚未解释。不能把10:30自行改称报告时间。",
        "- 截图展示口岸附近明显的河道/地表外观变化，只作定性旁证；没有地理配准、比例与独立核验的获取时间，不据图计算面积、深度、流量或确认日期。",
        f"- 本轮最后使用标签为{anchor}（北京时间）。从冰崩起始所属整点再退1小时；仅是保守标签选择，不等于已验证观测支持区间、无信息泄漏或业务可得性。",
        "",
        "## 方法与公式",
        "",
        "1. 原8包及配置记录哈希。小时CSV一次读取，保留源值；9999.9/非数值/非有限值只在派生统计视图中掩膜，不插值、不填零、不裁剪。",
        "2. 主口径QC0，敏感性口径QC0+4（提供方插补）；13个预定义指标、7个物理类别。同步差值要求各分量在同一标签有效。气温/相对湿度/标量风速梯度均为(20m−2m)/18m；土温梯度为(T0.8−T0.1)/0.7m；净辐射为Rsd−Rsu+Rld−Rlu。",
        "3. 案例窗取最后24/48/72个整点标签（首尾均含），有效数至少ceil(0.75×窗口长度)才取中位数；主窗72标签即8月23日10:00—26日09:00。小时支持区间未知，因此不声称精确覆盖对应72小时的物理积分。",
        "4. 参照为2022—2025各年8月26日前后15日，同09:00结束的同长度窗口，共124个候选参照窗。参照窗可能有灾害，不能叫可靠负样本；相邻窗口重叠，不能把124当独立样本。每指标有效参照窗至少60，否则不给排序。",
        "5. p=[参照中位数低于案例值的个数+0.5×相等个数]/有效参照窗数；D=2p−1。它是案例窗在经验分布中的位置，绝非灾害相关系数或致灾概率。辅助robust_z=(案例−参照中位数)/(1.4826MAD)，MAD为0时不给z值。",
        "6. 在每类别内取|D|最大的代表，再按|D|排各类别，取前五；并列按预定义指标顺序处理。该同例选择可能放大差异，属于探索，不输出p值或显著性声明。不同变量的中位数对周期/能量等物理问题表达能力不同，排名受候选集和统计量限制。",
        "7. 另检查24/48/72标签、两种QC和主窗逐个留出历史年的10个情景，按所有7类别计算名次。它们共用事件并非外部验证；输出排名变动和代表指标变化，不只展示稳定的情景。",
        "8. 极端背景只作经验尾部描述：历年同期、同钟点的小时值5%/95%分位为参照，对案例窗逐标签比较。不是官方极端事件标准，不是返回期或显著性检验。",
        "",
        "## 天气过程与极端背景",
        "",
        "下表给出前五代表在主窗的同期同钟点尾部记录。低/高尾部方向不等于灾害风险方向。",
        "",
        "| 指标 | 可比较标签 | 低于5%分位 | 高于95%分位 | 两侧合计比例 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in top.itertuples():
        t = tails.loc[tails.feature.eq(r.feature)].iloc[0]
        lines.append(
            f"| {r.name} | {int(t.comparable_labels)} | {int(t.lower_tail)} | {int(t.upper_tail)} | {t.tail_fraction:.1%} |"
        )
    lines += [
        "",
        "![因素对照](../output/question1/factor_contrast.png)",
        "",
        "![过程与小时参照](../output/question1/case_process.png)",
        "",
        "图中经验背景带不是置信区间；仅凭此站过程，不能确认灾区有局地强降水、强对流、特定天气系统或其触发作用。天气过程在首版限于塔站多变量过程及历史参照，待WRF/GFS补齐后才能扩展局地天气诊断。",
        "",
        "## 边界层结构与长期变量关系",
        "",
        "已完成并复用[同刻五高度剖面](vertical-profiles.md)和[非降水变量关系](variable-relations.md)。全高结构按同一时刻的共同有效掩膜计算；2—20m气温梯度为正的比例约27.32%，不能因此认定静力稳定或冰崩触发。风速梯度为标量差，未用它冒充矢量风切变。",
        "既有年×月中心化关系可展示季节共变影响，但变量互相关不参与本轮灾害背景前五排名，避免把Ta2与Ta20的高度同相关误当成两个独立致灾因子。",
        "",
        "## FLUX与降水的处理",
        "",
        "FLUX在现有审计中已检查全部25个字段，本轮另列H、LE、USTAR、TKE、TAU的原数值背景对照，见flux_context.csv。FLUX没有对应QC，‘可解析数值’不意味着质量合格；不与QC0排序混排，不据其计算稳定度或能量闭合。",
        "",
        "| FLUX字段 | 主窗数值标签 | 案例中位数 | 参照窗数 | 质量状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in flux.itertuples():
        lines.append(
            f"| {r.field} | {r.event_valid_labels} | {r.event_median:.5g} | {r.reference_n} | 无对应QC；仅数值描述 |"
        )
    lines += [
        "",
        "Precip原记录保留在raw_precipitation_records.csv，未筛成QC0，未求和、差分或累计；其区间/清零含义未确认，不能给雨强、前期累计降水或‘无雨’结论。土壤是塔站背景，不能替代跨境源区物源含水与冻土状态。",
        "",
        "## 敏感性、复现和交付",
        "",
        "![名次敏感性](../output/question1/rank_sensitivity.png)",
        "",
        "前五表同时保存10情景入选五类的次数、最差类别名次。若指标代表变动或窗口名次变化，论文必须披露，不能把某一方案的名次写成稳定普适排序。",
        "",
        "执行：`conda activate mc-base` 后在项目根目录运行 `python scripts/complete_question1.py`；也可 `python scripts/run_pipeline.py --steps question1`。仅此步骤即可复算本轮，不必重跑空间审计。原始8包按README放置。",
        "",
        "- 主结果：output/question1/top5_factors.csv；完整候选与比较：candidate_scores.csv、reference_windows.csv。",
        "- 覆盖与极端背景：hourly_reference_bands.csv、case_hourly_features.csv、empirical_tail_counts.csv。",
        "- 敏感性：ranking_sensitivity.csv，含每一类/每个情景名次及实际代表指标。",
        "- 方法/结果索引：output/question1/README.md；全量校验：verification.json；原始时间上下文：config/event-context.json。",
        "- 首版支撑包：output/deliverables/Question1_support_v1.zip；不含赛题原包，不代表四问最终提交包。",
        "- 上述定义与参数固定在config/question1.json；无随机拟合与随机重采样。路径按脚本位置定位，不依赖原作者电脑目录。",
        "",
        "当前限制：单案例，无独立灾害/无灾害标签，塔站距口岸约65 km，小时支持区间与观测延迟未知，局地气象资料未到，灾害时刻为用户报告且与赛题有冲突。首版可为论文提供诚实的区域背景结果，但题意中的普适关联排名和局地机制仍需补充证据。",
        "",
    ]
    (ROOT / "docs/question1-v1.md").write_text("\n".join(lines), encoding="utf-8")


def package_outputs():
    readme = """# 第一问首版支撑材料\n\n本包为区域背景案例对照首版，不是四问最终提交包。\n\n## 复现\n\n1. conda env create -f environment.yml，然后conda activate mc-base。\n2. 按config/input-manifest.json将原8包放入data/附件/（本包按要求不含原包）。\n3. python scripts/complete_question1.py。原包只读，输出在output/question1/。\n4. 阅读docs/question1-v1.md和top5_factors.csv；图表均配套数值来源。\n\n## 队友使用\n\n请引用“案例前背景对照前五类别”，保留单案例、区域站点及未验证时间来源等限制。\n正文方法、公式、每个结果的入口与图注在docs/question1-v1.md；边界层/变量关系原报告及图随包附上。\n5%—95%小时经验背景带不是置信区间；D不是致灾概率或因果系数。\n截图不参与数值计算，不随此包重复分发；事件时间为用户报告，需保留来源状态。\n\n本包不捆绑运行环境、个人路径、原始赛题数据和联网缓存。\n"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    files = [
        ROOT / "scripts/complete_question1.py",
        ROOT / "scripts/project_runtime.py",
        ROOT / "tests/test_question1.py",
        ROOT / "environment.yml",
        ROOT / "environment.win-64.lock.txt",
        ROOT / "PROGRESS.md",
    ]
    files += list((ROOT / "config").glob("*.json")) + [ROOT / "config/analysis-constraints.yml"]
    files += [
        ROOT / f"docs/{name}.md"
        for name in [
            "question1-v1",
            "vertical-profiles",
            "variable-relations",
            "metadata-review",
            "pending-questions",
        ]
    ]
    files += [p for p in OUT.iterdir() if p.is_file() and p.name != "support_manifest.json"]
    for folder, stems in [
        (
            "vertical_profiles",
            ["clock_cycles", "monthly_clock_gradients", "selected_full_profiles"],
        ),
        ("variable_relations", ["correlation_heatmaps", "year_variability"]),
    ]:
        for stem in stems:
            for ext in ["png", "svg"]:
                p = ROOT / "output" / folder / f"{stem}.{ext}"
                if p.exists():
                    files.append(p)
    manifest = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in sorted(set(files))}
    (OUT / "support_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dest = ROOT / "output/deliverables/Question1_support_v1.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(dest, "w", ZIP_DEFLATED) as z:
        z.writestr("README.md", readme)
        for p in sorted(set(files)):
            z.write(p, p.relative_to(ROOT).as_posix())
        z.write(OUT / "support_manifest.json", "output/question1/support_manifest.json")
    with ZipFile(dest) as z:
        if z.testzip() is not None:
            raise ValueError("Support ZIP CRC failed")
        for name, digest in manifest.items():
            import hashlib

            if hashlib.sha256(z.read(name)).hexdigest() != digest:
                raise ValueError("Support entry hash mismatch: " + name)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-package",
        action="store_true",
        help="Recompute numeric results without rewriting support ZIP",
    )
    args = parser.parse_args()
    cfg = json.loads((ROOT / "config/question1.json").read_text(encoding="utf-8"))
    context = json.loads((ROOT / "config/event-context.json").read_text(encoding="utf-8"))
    before = verify_input_files()
    constraint_hash = sha256_file(ROOT / "config/analysis-constraints.yml")
    OUT.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    views = {
        "qc0": features_from_raw(raw, cfg["primary_qc"]),
        "qc0_plus4": features_from_raw(raw, cfg["sensitivity_qc"]),
    }
    anchor = last_label(context["ice_collapse_onset"], cfg["last_label_guard_hours"])
    scores, windows = compute_tables(views, anchor, cfg)
    primary = scores.loc[
        scores.view.eq("qc0")
        & scores.hours.eq(cfg["primary_window_hours"])
        & scores.omitted_year.isna()
    ]
    top = select_families(primary)
    if len(top) != 5:
        raise ValueError("Fewer than five eligible distinct families; do not fabricate top five")
    sensitivities = []
    # All seven families ranked in each scenario, even when not selected in top five.
    for (view, hours, omitted), part in scores.groupby(
        ["view", "hours", "omitted_year"], dropna=False, sort=True
    ):
        ranked = (
            part.assign(abs_D=part.D.abs())
            .dropna(subset=["D"])
            .sort_values(["abs_D", "order"], ascending=[False, True])
            .drop_duplicates("family")
        )
        scenario = f"{view}_{hours}h" + (f"_omit{int(omitted)}" if pd.notna(omitted) else "")
        for rank, r in enumerate(ranked.itertuples(), 1):
            sensitivities.append(
                dict(
                    scenario=scenario,
                    family=r.family,
                    representative=r.feature,
                    family_rank=rank,
                    D=r.D,
                    reference_n=r.reference_n,
                )
            )
    sensitivity = pd.DataFrame(sensitivities)
    for i, r in top.iterrows():
        ranks = sensitivity.loc[sensitivity.family.eq(r.family), "family_rank"]
        top.loc[i, "top5_scenarios"] = int(ranks.le(5).sum())
        top.loc[i, "total_scenarios"] = sensitivity.scenario.nunique()
        top.loc[i, "worst_family_rank"] = int(ranks.max())
    bands = hourly_bands(views["qc0"], cfg)
    labels = pd.date_range(end=anchor, periods=cfg["primary_window_hours"], freq="h")
    case = views["qc0"].reindex(labels)
    tails = []
    for key, _, _, _, _ in FEATURES:
        b = bands.loc[bands.feature.eq(key)].set_index("hour").reindex(labels.hour)
        v = case[key].to_numpy()
        valid = np.isfinite(v) & np.isfinite(b.q05.to_numpy()) & np.isfinite(b.q95.to_numpy())
        lo = int(((v < b.q05.to_numpy()) & valid).sum())
        hi = int(((v > b.q95.to_numpy()) & valid).sum())
        tails.append(
            dict(
                feature=key,
                comparable_labels=int(valid.sum()),
                lower_tail=lo,
                upper_tail=hi,
                tail_fraction=(lo + hi) / valid.sum() if valid.sum() else np.nan,
            )
        )
    tails = pd.DataFrame(tails)
    fluxrows = []
    for field in ["H(W/m2)", "LE(W/m2)", "USTAR(m/s)", "TKE(m2/s2)", "TAU(kg/m*s2)"]:
        s = clean_field(raw["FLUX"], field, None)
        med, n = window_summary(s, anchor, 72, cfg["minimum_window_coverage"])
        refs = [
            window_summary(s, a, 72, cfg["minimum_window_coverage"])[0]
            for a in reference_anchors(anchor, cfg["reference_years"], 15)
        ]
        fluxrows.append(
            dict(
                field=field,
                event_valid_labels=n,
                event_median=med,
                quality="QC_not_provided",
                **contrast(med, refs, cfg["minimum_reference_windows"]),
            )
        )
    flux = pd.DataFrame(fluxrows)
    for name, t in [
        ("top5_factors.csv", top),
        ("candidate_scores.csv", scores),
        ("reference_windows.csv", windows),
        ("ranking_sensitivity.csv", sensitivity),
        ("hourly_reference_bands.csv", bands),
        ("case_hourly_features.csv", case.reset_index(names="Timestamp")),
        ("empirical_tail_counts.csv", tails),
        ("flux_context.csv", flux),
    ]:
        save_csv(name, t)
    precip = raw["MET"].reindex(labels)[["Precip(mm)"]].reset_index()
    save_csv("raw_precipitation_records.csv", precip)
    figures(
        primary,
        top,
        case,
        bands,
        sensitivity,
        pd.Timestamp(context["ice_collapse_onset"]).tz_localize(None),
    )
    checks = {
        "raw_archive_hashes_unchanged": before == verify_input_files(),
        "global_constraints_unchanged": constraint_hash
        == sha256_file(ROOT / "config/analysis-constraints.yml"),
        "five_distinct_families": len(top) == 5 and top.family.nunique() == 5,
        "13_predefined_candidates": len(primary) == len(FEATURES) == 13,
        "no_event_year_reference": windows.year.lt(2026).all(),
        "reference_clock_matched": pd.to_datetime(windows.anchor).dt.hour.eq(anchor.hour).all(),
        "124_reference_candidates_per_metric_view_window": windows.groupby(
            ["view", "hours", "feature"]
        )
        .size()
        .eq(124)
        .all(),
        "source_labels_not_duplicated": all(v.index.is_unique for v in views.values()),
        "no_onset_hour_or_post_onset_label": case.index.max() == anchor
        and anchor < pd.Timestamp("2026-08-26 10:00"),
        "all_primary_windows_have_adequate_coverage": primary.event_valid_labels.ge(54).all(),
        "rank_D_in_bounds": scores.D.dropna().between(-1, 1).all(),
        "10_sensitivity_scenarios": sensitivity.scenario.nunique() == 10,
        "flux_not_in_QC_ranking": not any(k in set(top.feature) for k in flux.field),
        "no_precipitation_derived_feature": not any(
            "precip" in k.lower() or "rain" in k.lower() for k in case.columns
        ),
        "trigger_exact_stays_unknown": context["debris_flow_trigger_exact"] is None,
    }
    checks = {k: bool(v) for k, v in checks.items()}
    evidence = dict(
        passed=all(checks.values()),
        checks=checks,
        checked_at_utc=datetime.now(timezone.utc).isoformat(),
        input_hashes=before,
        config_hashes={
            p.name: sha256_file(p)
            for p in [ROOT / "config/question1.json", ROOT / "config/event-context.json"]
        },
        event_source_status=context["source_status"],
        latest_used_label=str(anchor),
        interpretation="single-case regional background contrast; no causal/hazard probability or independent validation claim",
    )
    (OUT / "verification.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not evidence["passed"]:
        raise ValueError("Question-one data checks failed: " + str(checks))
    make_report(top, scores, tails, flux, anchor, context, cfg, evidence)
    # A stable result index: updating this file does not require reading the chat.
    progress = f"""# 项目完成情况\n\n更新：{datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="minutes")}；截止2026-10-30 20:00北京时间。\n\n| 内容 | 状态 | 查看位置 |\n| --- | --- | --- |\n| 环境、原8包审计、来源定义和复现 | 已完成本轮 | README.md；docs/data-audit.md |\n| 第一问 | 首版已计算并交付：区域背景案例对照，五因素、过程和敏感性 | [第一问报告](docs/question1-v1.md)；[五因素表](output/question1/top5_factors.csv) |\n| 第一问局地机制/普适关联验证 | 待局地资料与事件目录；不得视为已验证 | docs/question1-v1.md限制部分 |\n| 第二问触发评估 | 尚未完成 | docs/data-request-and-delivery.md |\n| 第三问时间/空间预报 | 尚未完成；触发仅为条件区间约束 | config/event-context.json |\n| 第四问过程仿真 | 尚未完成 | docs/data-request-and-delivery.md |\n| 支撑材料 | 第一问首版包已生成；四问最终包未生成 | output/deliverables/Question1_support_v1.zip |\n\n第一问运行：`conda activate mc-base` 后 `python scripts/complete_question1.py`。无需重跑其他审计。\n\n本轮{len(checks)}项数据一致性校验通过；校验只证明程序及计数一致，不证明灾害机制或预报能力。\n\n新事件时间为用户报告、未独立核验，与赛题10:30冲突保留。前后截图只作定性参考，原始小时数据未改动、未新增填补、未生成累计降水特征。\n"""
    (ROOT / "PROGRESS.md").write_text(progress, encoding="utf-8")
    if not args.no_package:
        package_outputs()
    print(
        top[
            [
                "family",
                "name",
                "event_median",
                "reference_median",
                "percentile",
                "D",
                "top5_scenarios",
                "worst_family_rank",
            ]
        ].to_string(index=False)
    )
    print(f"PASS {len(checks)} data checks. Report: docs/question1-v1.md; progress: PROGRESS.md")


if __name__ == "__main__":
    main()
