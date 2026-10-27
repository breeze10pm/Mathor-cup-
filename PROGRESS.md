# 项目完成情况

更新：2026-10-27T20:56+08:00；截止2026-10-30 20:00北京时间。

| 内容 | 状态 | 查看位置 |
| --- | --- | --- |
| 环境、原8包审计、来源定义和复现 | 已完成本轮 | README.md；docs/data-audit.md |
| 第一问 | 首版已计算并交付：区域背景案例对照，五因素、过程和敏感性 | [第一问报告](docs/question1-v1.md)；[五因素表](output/question1/top5_factors.csv) |
| 第一问局地机制/普适关联验证 | 待局地资料与事件目录；不得视为已验证 | docs/question1-v1.md限制部分 |
| 第二问触发评估 | 尚未完成 | docs/data-request-and-delivery.md |
| 第三问时间/空间预报 | 尚未完成；触发仅为条件区间约束 | config/event-context.json |
| 第四问过程仿真 | 尚未完成 | docs/data-request-and-delivery.md |
| 支撑材料 | 第一问首版包已生成；四问最终包未生成 | output/deliverables/Question1_support_v1.zip |

第一问运行：`conda activate mc-base` 后 `python scripts/complete_question1.py`。无需重跑其他审计。

本轮15项数据一致性校验通过；校验只证明程序及计数一致，不证明灾害机制或预报能力。

新事件时间为用户报告、未独立核验，与赛题10:30冲突保留。前后截图只作定性参考，原始小时数据未改动、未新增填补、未生成累计降水特征。
