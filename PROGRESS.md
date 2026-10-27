# 项目完成情况

更新：2026-10-27（UTC+8）；截止2026-10-30 20:00北京时间。

| 内容 | 状态 | 查看位置 |
| --- | --- | --- |
| 环境、原8包审计、来源定义和复现 | 已完成本轮 | README.md；docs/data-audit.md |
| 第一问 | 首版已计算并交付：区域背景案例对照，五因素、过程和敏感性 | [第一问报告](docs/question1-v1.md)；[五因素表](output/question1/top5_factors.csv) |
| 第一问局地机制/普适关联验证 | 待局地资料与事件目录；不得视为已验证 | docs/question1-v1.md限制部分 |
| 第二问触发评估 | 已开始：冰川源区、GFS、岩屑坡和河网的QGIS首批图层已生成；阈值/路线模型待源区与口岸坐标和河名对应核对 | [第二问首版记录](docs/question2-v0.md)；`output/question2/initial_layers/` |
| 第三问时间/空间预报 | 尚未完成；触发仅为条件区间约束 | config/event-context.json |
| 第四问过程仿真 | 尚未完成 | docs/data-request-and-delivery.md |
| 支撑材料 | 第一问首版包已生成；四问最终包未生成 | output/deliverables/Question1_support_v1.zip |

第一问复算：`conda activate mc-base` 后运行 `python scripts/complete_question1.py`，无需重跑其他审计。第二问准备层：同一环境运行 `python scripts/prepare_question2_layers.py`。

第一问15项数据一致性校验已通过。第二问首批图层已写出；河网11线、岩屑坡261面；原始Shapefile哈希已记录，缺失的岩屑坡SHX只在临时副本重建。这只证明数据可读取，不证明灾害机制或模型能力。

NCDC应急专题目录可见灾前0.5m DOM（2.6GiB）、DEM8m（57MiB）、GF7灾前（3.1GiB）/灾后（7.9GiB）影像。建议先由用户下载DEM8m；若目标是尽量从影像估计堆积厚度，再考虑GF7前后立体影像，需检查RPC/立体覆盖与精度后才能判断是否可用。0.5m DOM适于灾前地表/沟道判读；不是高程模型。视频暂不需要。当前NCDC页面可被搜索索引读取，但页面直接打开返回502；下载/登录由用户网页端操作。详见第二题记录。

新事件时间为用户报告、未独立核验，与赛题10:30冲突保留。前后截图只作定性参考，原始小时数据未改动、未新增填补、未生成累计降水特征。
