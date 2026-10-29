# 方法与算法版本

Q1：QC/缺失规则、同季同钟点历史比较、五类因素经验分位。新增WRF D01/D02描述，不更改排名。
Q2：源区失稳、沟道物源/水源转化、下游传播的条件分层；缺失水源保持未知。场景评分不代表概率。
Q3：区分冰崩起始、转化阶段、物理触发、到达。模式起报不等于公开可得；反推速度的条件到达不是独立预测。
Q4：状态h、q=hu，质量与动量守恒，HLL通量、水静力重构、Voellmy摩擦、CFL时步。旧版源码question4_dynamics_v1_reference.py保留，question4_dynamics.py仅已有像元取样floor修正；build_question4_simulation.py没有切换到candidate。
question4_boundary_candidate.py检验入口质量/动量一致性；question4_friction_candidate.py为静摩擦平衡候选。缓存由源码SHA与输入数组SHA隔离。固定候选SHA和参数见../support_materials/research/q4_acceptance/provenance.json。
候选参考V=600000m³、B=100m、T=120s、入口h=3m、μ=0.1、ξ=300m/s²、窗口1800s，均为未本地校准假设，不随网格调整。6.25m细化共享25m母剖面，不增加观测信息。
