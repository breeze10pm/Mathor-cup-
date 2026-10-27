"""汇总已生成的表格和空间审计证据，输出供讨论的中文报告。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "output/data_audit/tabular"
SPATIAL = ROOT / "output/data_audit/spatial"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def markdown_table(frame: pd.DataFrame) -> str:
    """无需额外 tabulate 依赖，保留审计表中的数值与明确列名。"""
    clean = frame.fillna("—").astype(str)
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    rows = [
        "| " + " | ".join(map(escape, clean.columns)) + " |",
        "| " + " | ".join(["---"] * len(clean.columns)) + " |",
    ]
    rows.extend("| " + " | ".join(map(escape, row)) + " |" for row in clean.to_numpy())
    return "\n".join(rows)


def main() -> None:
    summary = read_json(TAB / "summary.json")
    spatial = read_json(SPATIAL / "spatial_summary.json")
    files = pd.read_csv(TAB / "hourly_files.csv")
    fields = pd.read_csv(TAB / "field_dictionary.csv")
    quality = pd.read_csv(TAB / "hourly_field_quality.csv")
    daily = pd.read_csv(TAB / "daily_temperature_files.csv")
    windows = pd.read_csv(TAB / "pre_event_availability.csv")
    distribution = pd.read_csv(SPATIAL / "historical_distributions.csv")
    latest = files.loc[files.year == 2026].copy()
    latest["疑似缺测占比"] = latest.diagnostic_unavailable_fraction.map(
        lambda value: f"{value:.2%}"
    )
    hourly_view = latest[
        [
            "group",
            "measurement_columns",
            "rows",
            "last_diagnostic_nonmissing_timestamp",
            "疑似缺测占比",
        ]
    ].rename(
        columns={
            "group": "数据组",
            "measurement_columns": "测量字段数",
            "rows": "全年时间标签数",
            "last_diagnostic_nonmissing_timestamp": "最后诊断非缺测时间",
        }
    )
    bounds = spatial["dem_historical_coverage"]
    source = spatial["dem_source_coverage"]
    populations = pd.read_csv(SPATIAL / "population_attributes.csv")
    population = populations.iloc[0]
    old = files.loc[files.year < 2026].pivot(
        index="year", columns="group", values="diagnostic_unavailable_fraction"
    )
    old = old.map(lambda value: f"{value:.2%}").reset_index().rename(columns={"year": "年份"})
    dates = daily.loc[daily.year == 2025].iloc[0]
    w72 = windows.loc[windows.hours == 72]
    qc_flags = int(w72.qc_nonzero_count.sum())
    repeated = sum(row["all_measurements_identical"] for row in summary["cross_year_comparisons"])
    physical = quality.loc[
        quality.range_flag_count > 0, ["group", "year", "field", "range_flag_count", "min", "max"]
    ].rename(
        columns={
            "group": "数据组",
            "year": "年份",
            "field": "字段",
            "range_flag_count": "范围标记数",
            "min": "诊断最小值",
            "max": "诊断最大值",
        }
    )
    manifest = pd.DataFrame(summary["source_archives"])
    manifest["压缩大小MiB"] = (manifest.bytes / 1048576).round(2)
    inventory = manifest[["attachment", "archive", "压缩大小MiB"]].rename(
        columns={"attachment": "附件", "archive": "文件"}
    )
    future_cells = int(latest.post_audit_date_available_cells.sum())
    total_cells = int(files.measurement_cells.sum())
    parse_tokens = int(files.nonnumeric_token_cells.sum())
    missing_cells = int(files.native_missing_cells.sum())
    sentinel_cells = int(files.candidate_sentinel_cells.sum())
    type_counts = distribution.loc[distribution.field == "类型", ["value", "count"]].rename(
        columns={"value": "类型", "count": "历史面数"}
    )
    report = f"""# 第一阶段数据审计报告

审计日：{summary["audit_date"]}。范围为用户确认的8组官方原始附件。
本阶段完成数据清点、字段字典、时间与空间覆盖、缺失/异常诊断和探索图；不产生模型评分、特征重要性或预报结论。

## 应先看到的结论

1. 24份小时CSV包含4类数据、63个测量字段、37个QC字段。每组有52,584个不重复小时标签；这不代表有52,584次灾害。
2. 四组2026年数据的最后诊断非缺测时间均为2026-08-27 08:00。文件排到12月31日，审计日之后的诊断非缺测测量单元格为{future_cells}，不能把后续时间标签当作真实观测。
3. 题设事件前72小时，63个测量字段均有数值；其中有QC字段的测量单元格出现非零QC码{qc_flags}次。QC语义未附说明，“有数值”不等于“已通过质量验收”。
4. 历史清单是84个灾害多边形，flag均为1，未提供明确灾害发生时间字段。影像/解译日期不能当作事件日期；未记录地点不能自动当成负样本。
5. DEM仅与{bounds["polygon_intersects_dem"]}/84个历史面相交，完整包含{bounds["polygon_fully_in_dem_bounds"]}/84个历史面；但覆盖附件4冰川掩膜全部{source["glacier_mask_cells"]:,}个像元中心。源区与县域历史样本需分开定义研究范围。
6. 土地覆盖图在附件4冰川源区没有有效分类值；人口只有县级一条汇总，不能直接计算沟谷或淹没区内的精确暴露人口。

## 1. 输入与可复现记录

{markdown_table(inventory)}

7个ZIP全部成员已通过CRC检查。8个原始包均记录SHA-256，RAR解压与全部栅格读取结果见空间审计。
原始附件不覆盖；表格直接从包内读取。空间副本在`data/extracted/spatial/`，全部审计输出位于`output/data_audit/`。

本次表格审计共检查{total_cells:,}个测量单元格，区分默认空值/缺失标记{missing_cells:,}个、额外非数值标记{parse_tokens:,}个和候选数值哨兵{sentinel_cells:,}个。
额外非数值标记主要为大写`NAN`，不能只用默认空值统计检查湍流数据。
脚本同时记录无穷值，并对各类计数进行分解核验。

## 2. 小时观测

{markdown_table(hourly_view)}

以上缺测占比以全年时间标签和测量单元格为分母，包含尚无观测的年末区间，并非仅针对实际运行期的仪器故障率。
候选哨兵诊断使用{summary["policies"]["candidate_missing_codes"]}，不据此替代官方缺测定义。
观测到QC码为{", ".join(summary["qc_codes_observed"])}。原始数值和QC码保留在原始包中，诊断视图另存Parquet，掩膜规则与计数有单独记录。审计没有插值、填零、裁剪或直接删除非零QC记录。

![小时缺测诊断](../output/data_audit/tabular/hourly_missingness.png)

2021—2025年按相同口径的测量单元格疑似缺测占比：

{markdown_table(old)}

2021年也存在较长缺测区间，不能把全年的时间标签都当作可用样本。
四组小时标签均按时间排列、无重复，标准小时日历未发现标签缺口；字段结构逐年一致性已单列核验。
对4组数据做了{len(summary["cross_year_comparisons"])}组跨年同月日小时精确比较（去除2月29日），发现全年全部测量值相同的配对为{repeated}。该检查不能证明数据来源或所有局部片段均独立。

![2026有效数据时间轴](../output/data_audit/tabular/availability_2026.png)

### 2.1 题设事件窗口

事件名义时间按题目2026-08-26 10:30记录；源文件未声明时区。72小时诊断窗口采用`2026-08-23 10:00 ≤ 标签 < 2026-08-26 10:00`，排除可能跨越10:30的整个10点小时。
后续正式预警分析还必须确认时间标签表示区间起点、终点还是瞬时值，以及数据实际发布时间。

![事件窗口诊断](../output/data_audit/tabular/event_window_diagnostics.png)

图中日均只在至少18小时有数值时展示。降水图仅对24小时均非缺测的日求字段值之和，累计区间与仪器计量方式未确认，因此还不能直接当作正式日降水量或用于求触发阈值。
这些曲线用于检查数据形态，不将单次事件前的变化解释为因果关系。

### 2.2 范围标记

{markdown_table(physical)}

相对湿度略高于100%和土壤体积含水率1.64均列为待核查记录，未直接裁剪。
辐射负值可能涉及夜间零偏，IQR尾部值可能是真实极端事件，均不按通用异常规则自动删除。
MET气压单位为hPa，FLUX的PA为kPa，后续如比较需显式转换并考虑观测高度/仪器差异；风向须按圆周量处理。
CSV未包含站点经纬度和空间维度，不能推定它覆盖整个吉隆县或冰崩源区。

## 3. 五县逐日气温

21份Excel合计{summary["daily_temperature_rows"]:,}天、5县。
2005—2024为完整日历年；2025只有{dates["rows"]}天，时间为{dates["start"]}至{dates["end"]}，缺少年末{dates["missing_calendar_days"]}天。不得与完整年份直接比较全年均值。
未发现重复日期、非法日期或表内缺失单元格；表尾缺少时段与“表内无空值”是不同问题。

![完整年份气温均值](../output/data_audit/tabular/annual_temperature_complete_years.png)

包内来源说明将其归为ERA5-Land再分析日统计。CDS原产品2米气温单位为K，日统计允许选择UTC偏移；附件Excel已有负数而标题没有单位。可能已经转换为摄氏温度，但转换步骤、县域汇总方式和日界线需核对，审计不再次减273.15。
来源与解释边界见[数据来源记录](data-provenance.md)，[CDS产品说明](https://cds.climate.copernicus.eu/datasets/derived-era5-land-daily-statistics?tab=overview)。再分析数据适合历史背景分析，不能冒充预警时刻已发布的天气预报。

## 4. 历史灾害与空间范围

历史图层84个Polygon，EPSG:4490。类型分布、影像/解译时间、几何有效性和坐标覆盖见[空间审计报告](spatial-audit.md)。

{markdown_table(type_counts)}

`解译Time`全部为2020-07-25，`影像Time`范围为2010—2017；均不解释为发生日期。
flag全部为1且缺少业务定义，不能直接构造有可信负样本的灾害二分类训练集。
每条历史面的相交、完整包含、有效像元覆盖和属性点可采样性分别记录，不能用“有一点相交”代替整条沟谷有地形数据。
历史图层`Resolution`列的非空值实际为“吉隆河”，不能按列名把它解释成数值分辨率；属性面积、距离等仍需核对单位字典。

![空间覆盖](../output/data_audit/spatial/spatial_coverage.png)

DEM本身无NoData，但局部DEM不能代表县域完整地形覆盖。DEM为经纬度栅格，像元单位是度；坡度、距离、面积、流路长度等需使用明确的投影或椭球计算。
附件4的30m冰川网格具有2014—2024速度气候态，2018年时间截距；不存在事件前逐日速度序列。双线性重采样到30m也不代表所有输入原生分辨率均为30m。
附件3为2000—2020分段冰川高程变化，不能直接作为2026年实时融水量。
土地覆盖2020—2023须保留原始分类代码，分类字典未确认；源区NoData不能改填成某个类别。
RGI6存在1个自相交几何，已记录原ID和原因；未自动修复。NetCDF的`v`与当前`vx/vy`合成模长有差异，最大约0.495m/年，已保留为源数据一致性告警，不修改原值；可能与分别重采样有关，但未证实。
人口为县级汇总：`合计`={int(population["合计"]):,}、`人口数`={int(population["人口数"]):,}，口径不同，不相互覆盖，也不能均匀分摊后声称得到真实村落或沟谷人口。

## 5. 对四问的直接影响

| 问题 | 当前可推进内容 | 需要约束的结论 |
| --- | --- | --- |
| 第一问关联特征 | 观测质量处理、季节背景、事件窗口和物理意义特征探索 | 先定义比较目标，不能从单次事件声称稳定因果排序 |
| 第二问触发评估 | 物理条件梳理、候选参数与情景/历史清单分析 | 触发临界值的经验验证依赖可信事件和未发生记录 |
| 第三问预报与95%区间 | 设计严格的数据可得时刻、区间定义及回测方案 | 缺少独立带时标事件时，不能宣称验证了95%覆盖率 |
| 第四问仿真 | 在DEM覆盖的源区与通道上讨论合理情景和参数范围 | 地形可用不等于流量、流变参数和真实灾害过程已标定 |

随机分层五折不作为默认方案。相邻小时、同一灾害面内像元和同次事件的重复窗口不能随意跨训练与验证集合；先明确验证对象与独立单位，再决定折数及时间/空间分组。

## 6. 下一阶段需要共同确定

优先进入第一问：先讨论观测时间与QC口径、事件对照窗口和候选特征的物理解释，再实施分析。
若暂时无法取得站点/QC说明，所有相关分析应明确条件，并比较不同合理处理口径的敏感性。
不把“影像时间改成发生时间”“未记录地点改成负样本”“缺失降水填成0”作为便捷替代。
后续需要补充真实事件时间、业务可用的天气预报或更大范围DEM时，另列来源、下载时间、许可和处理步骤。

## 7. 输出与重跑

- 字段字典：`output/data_audit/tabular/field_dictionary.csv`。
- 小时逐文件与逐字段质量：`hourly_files.csv`、`hourly_field_quality.csv`。
- QC码和事件窗口：`qc_code_counts.csv`、`pre_event_availability.csv`。
- 原始包SHA-256与CRC记录：`archive_manifest.json`。
- 诊断Parquet：保留来源字段名；仅将候选哨兵/非数值作诊断掩膜，不能直接当作最终建模输入。
- 空间完整证据和图表：`output/data_audit/spatial/`及[空间审计报告](spatial-audit.md)。

在项目根目录、已激活`mc-base`后运行：

```bat
python scripts/audit_tabular.py
python scripts/audit_spatial.py
python scripts/build_audit_report.py
python scripts/verify_data_audit.py
```

原始压缩包、解压数据和生成结果按现有Git规则排除，需另行备份；审计脚本及说明纳入版本管理。
"""
    target = ROOT / "docs/data-audit.md"
    target.write_text(report, encoding="utf-8")
    print(f"Report generated: {target}")


if __name__ == "__main__":
    main()
