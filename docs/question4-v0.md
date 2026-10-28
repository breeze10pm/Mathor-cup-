# 第四问：中心线约束下的一维传播情景

## 模型和关键参数

用公开沟道中心线把抽象的22 km里程轴换成地理坐标与沿程高程剖面。对源区A、B分别投影到中心线，并将TPDC口岸核心点投影到中心线：A路径22.156 km，B路径21.993 km。沿线中心高程约从4062/4022 m降到1801 m，平均落差约2221–2261 m、平均坡降约10.1–10.2%。这些是中心线属性，不是实际流面高程或现场测量误差。

用户报告的冰崩起始10:52与口岸到达10:59仍锚定整条灾害链平均路线速度，约52.36–52.75 m/s。新提供的碎屑流向泥石流转化关键时段为10:54:19–10:55:10，代表时刻按用户要求取10:54:19。脚本在时间—里程图标出该阶段，并计算恒定平均速度假设下的前锋位置情景。转化发生位置未知，因此这些里程只是模型演示，不能作为转化地点实测。±15%仍是分析者选定的演示参数，不是观测误差或95%区间；基准复现10:59属于构造校准，不是验证。

前锋位置按时间步沿中心线插值，输出里程、坐标、高程和剩余距离。结果可在QGIS上叠加源区、口岸核心区、UNESCO/UNOSAT范围。此方案满足可复现的地理化过程展示，但仍是一维运动学情景，**不是二维浅水、Voellmy或泥石流流变数值模拟**。

转化时间窗对应的沿线位置另存于`question4_transition_positions.csv`。位置由10:52开始时前锋恰在源区投影点、随后以全程平均速度匀速运动这一简化假设计算；由于转化的实际空间位置没有测量，不能用它反推真实转化点或局地流速。

在这个假设下，10:54:19代表时刻的模拟里程为A约7.33 km、B约7.28 km；到10:55:10为A约10.02 km、B约9.95 km。它只说明“若从源区投影点以全程平均速度匀速前进，模型前锋会在哪里”，不能作为实地转化位置。

![中心线路径和到达敏感性](../output/question4/question4_georeferenced_scenarios.png)

## 高程变化证据与厚度解释

v1.1发布的口岸河段校正dh栅格与其1σ不确定度相同网格、同为EPSG:32645，垂直基准EGM2008；项目在中心线采样，但只有29/611个沿线样点落入有效变化像元，因此只作为局部核对。分段床面预算显示，核心区附近km23.75、24.25的中位变化分别-9.68 m和-8.24 m；对应床面冲刷约0.2087、0.4031 Mm³，沉积约0.0055、0.0049 Mm³，覆盖率43%、99%。局部证据更支持“该河段以冲刷/下切为主”，不支持把负dh称作堆积厚度。v1.1数据本身说明A段水平配准较粗、覆盖有云洞，必须把不确定度和覆盖率一并报告。

2019源区DEM覆盖不到口岸；本地灾后DEM虽覆盖口岸，且与2019数据采用不同采集时期和处理链。v1.1采用EGM2008而本地DEM为WGS84椭球高，因此不跨产品直接相减。下游Syabrubesi沉积面不覆盖当前口岸核心区，也不挪用其沉积范围。

## 当前省略的物理量

- 冰岩崩和入沟物质量/体积、含水率及初始流量过程线；
- 沿途断面、流深、水痕、流速实测和真实到达时刻；
- 沟床粗糙度、摩阻/流变参数、侵蚀夹带及沉积规律；
- 通过独立边界或现场记录进行的校准与验证。

缺这些输入时，不输出流深、体积、沉积厚度或未经验证的淹没概率。UNESCO和UNOSAT范围只作为卫星解译空间参照。

## 复现和QGIS结果

在项目根目录、`mc-base`环境顺序运行：

```console
python scripts/prepare_event_context.py
python scripts/build_question4_kinematic.py
```

参数在 `config/question4-kinematic.json`，空间路径在`output/event_context/event_context.gpkg`。第四问输出：

- `output/question4/question4_summary.json`
- `output/question4/question4_arrival_sensitivity.csv`
- `output/question4/question4_front_trajectories.csv`
- `output/question4/question4_route_profile.csv`
- `output/question4/question4_transition_positions.csv`
- `output/question4/question4_local_sediment_budget.csv`
- `output/question4/question4_georeferenced_scenarios.png`

所有输入都用项目相对路径；原始数据、第三方栅格和生成缓存不提交GitHub。更多来源、许可证和数据质量说明见[新增空间资料核验](new-evidence-review.md)。
