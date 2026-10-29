# 吉隆泥石流灾害链研究

本项目整理2026年吉隆冰岩崩—碎屑流—泥石流—山洪灾害链的多源数据分析、分层条件评估、时间情景和一维动力学实验。研究阶段已结束；本仓库用于长期追溯和复现，不是经过现场校准的业务预报系统。

## 研究结果与边界

| 模块 | 已实现 | 不能据此宣称 |
|---|---|---|
| Q1 | 五类候选因素背景比较；D01/D02模式天气 | 普适因果因素排名或源区实测降水 |
| Q2 | 地形、物源与未知水源的分层条件评估 | 本地校准临界阈值或触发概率 |
| Q3 | 时间证据与检测后条件传播 | 已验证95%触发区间、覆盖率或业务提前量 |
| Q4 | 基线/候选一维有限体积、质量收支、网格试验 | 全链重建、整体严格收敛或实测堆积厚度 |

D02源区最近格点截至8月26日10:00北京时间前24h模式降水26.095mm，D01为10.948mm；D02口岸4.329mm。源区09—10h最近格点两域均0，但不代表整个源区灾前无雨。24h窗口起点距模式启动仅2h。A/B共享D02格点；两个嵌套域不是独立模型验证。

候选Q4在25/12.5/6.25m下的末时流深较接近，峰值速度和断面过程仍敏感；候选保留为探索性版本，没有替换旧版。所有结论限定于固定假设入沟条件。

## 快速开始

```console
conda env create -f environment.yml
conda activate mc-base
python -m unittest discover -s tests -v
python scripts/run_pipeline.py --dry-run
```

单元试验无需原始大数据。完整地理/气象实验需要合法取得外部数据，按[复现说明](docs/reproducibility.md)放置；不能直接用本仓库轻量图件替代原始输入。

## 阅读路径

- [研究范围](docs/overview.md) · [方法与版本](docs/methodology.md) · [数值验证](docs/validation.md) · [科学限制](docs/limitations.md)
- [数据来源与许可](docs/data_catalog.md) · [追溯关系](docs/provenance.md) · [版本历史](docs/changelog.md) · [AI辅助](docs/ai_assistance.md)
- [图表](docs/figures.md) · [论文增量](docs/paper/manuscript_update_notes.md) · [关键数字](docs/paper/numbers_master.csv)
- [成果盘点](docs/project_inventory.md) · [整理验收报告](docs/project_closeout_report.md)

scripts/config/tests保留现有路径；support_materials/research只含精选研究结果；data/output不整体分发；docs/archive与历史报告保留不利结果和研究过程。
代码许可证尚未由权利人确定。第三方数据、影像与派生产品遵循各自许可，不能因代码公开而视作无限制授权。
