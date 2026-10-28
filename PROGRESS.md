# 项目完成情况

更新：2026-10-28（UTC+8）；截止2026-10-30 20:00北京时间。

| 内容 | 状态 | 查看位置 |
| --- | --- | --- |
| 环境、原8包审计、来源定义和复现 | 已完成本轮 | README.md；docs/data-audit.md |
| 第一问 | 首版已计算并交付；新增站点事件窗零降水与WRF d01气象背景补充，未把单例改写为因果排名 | [第一问报告](docs/question1-v1.md)；[交叉核对](docs/video_crosscheck_20261028.md)；[五因素表](output/question1/top5_factors.csv) |
| 第一问局地机制/普适关联验证 | 待局地资料与事件目录；不得视为已验证 | docs/question1-v1.md限制部分 |
| 第二问触发评估 | 已升级为空间条件筛查：A/B源点、UNOSAT脱离区、双范围、河道中心线；没有训练标签，不报触发概率 | [第二问记录](docs/question2-v0.md)；[空间资料核验](docs/new-evidence-review.md)；`output/event_context/` |
| 第三问时间/空间预报 | 已纳入10:54:19–10:55:10转化阶段窗口，以10:54:19作为用户指定的代表情景；泥石流物理触发精确时刻和统计95%区间仍未知 | [第三问报告](docs/question3-v0.md)；`output/question3/`
| 第四问过程仿真 | 一维中心线前锋已标出转化阶段时间窗；恒速推算的位置是模拟情景，不是转化点观测；非二维水动力，未估计流深/堆积厚度 | [第四问报告](docs/question4-v0.md)；`output/question4/`
| 新增外部资料 | 已本地获取中心线、v1.1口岸段dh/1σ/实测DSM/预算；数据和第三方栅格按规则不进Git | [来源、许可和限制](docs/new-evidence-review.md)；`data/supplementary/geo-pera-v1.1/` |
| 数据性质与关键缺口 | 已逐题区分实测、遥感派生、天气模式和本项目情景模拟，并列出完成各问的关键缺口 | [数据来源与关键缺口](docs/data-provenance-and-critical-gaps.md) |
| 支撑材料 | 四问首版报告、程序和复现说明整理中；本次提交不含比赛原始数据、第三方原始/衍生大栅格 | `docs/`、`scripts/`、`config/`；QGIS本地层在`output/event_context/` |

第一问首版复算：`conda activate mc-base` 后运行 `python scripts/complete_question1.py`；WRF/事件窗补充运行 `python scripts/supplement_q1_wrf.py`。第二问与Q3/Q4新数据层：先运行`python scripts/prepare_event_context.py`，再运行 `python scripts/build_question3_baseline.py` 和 `python scripts/build_question4_kinematic.py`。本地缺文件时，先按`docs/new-evidence-review.md`的数据清单准备。

第一问15项数据一致性校验已通过。第二问首批图层已写出；河网11线、岩屑坡261面；原始Shapefile哈希已记录，缺失的岩屑坡SHX只在临时副本重建。这只证明数据可读取，不证明灾害机制或模型能力。

数据进展：8m DEM、0.5m灾前正射影像、GF7灾后压缩产品、GFS降水/云产品、d01 WRF文件均已在项目`data/`中。GF7灾前原始大包尚未取得；`data/evidence/`里的GF7 JPG只是预览图。WRF d02下载失败，d01约9 km网格可先作为模式背景。8m DEM有效区约0.94%为0高程，核验前不参与水文分析。TPDC遥感子目录另有8月27日长光六景0.5m RGB灾后影像与含RPC的资源三号灾前影像，先核对现有影像覆盖与RPC，缺覆盖再决定补下。TPDC报告核心区坐标85.3766°E、28.2785°N已记录；它不是源点或精确到达断面。详见第二题记录。

新事件时间仍为用户报告、未独立核实；赛题10:30冲突保留。10:54:19–10:55:10作为碎屑流向泥石流转化关键时段，10:54:19为代表情景，不自动称为触发真值；旧均匀先验已移除。数据是否为观测或模拟见`docs/data-provenance-and-critical-gaps.md`。v1.1口岸段dh在核心附近表现为负值/冲刷；不将其称作堆积厚度。用户前后截图只作定性参考，原始小时气象资料未改动、未新增填补、未生成未定义的累计降水特征。
