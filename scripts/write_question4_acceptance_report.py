"""Read existing supplement results and document bounded acceptance decisions."""
from supplement_question4_acceptance import OUT,save,integral,ratio
import pandas as pd
import numpy as np

def main():
    h=pd.read_csv(OUT/'section_1000_timeseries.csv'); spatial=pd.read_csv(OUT/'spatial_mass_timeseries.csv'); timing=[]; shifts=[]
    for dx,g in h.groupby('dx_m'):
        t=g.time_s.to_numpy(); q=g.Q_1000_m3_s.to_numpy(); peak=q.max(); plateau=t[q>=.99*peak]
        row=dict(dx_m=dx,peak_99pct_start_s=plateau[0],peak_99pct_end_s=plateau[-1],discharge_time_centroid_s=integral(t*q,t)/integral(q,t))
        for frac in [.1,.5,.9]:
            indices=np.flatnonzero(q>=frac*peak); row[f'rising_{frac:g}_s']=float(t[indices[0]]); row[f'last_above_{frac:g}_s']=float(t[indices[-1]])
        row['physical_integrated_volume_m3']=integral(q,t); row['numerical_net_volume_near1000_m3']=float(g.net_face_volume_m3.iloc[-1]); row['numerical_face_location_m']=float(g.nearest_face_m.iloc[0]); row['physical_vs_numerical_difference_m3']=row['physical_integrated_volume_m3']-row['numerical_net_volume_near1000_m3']; timing.append(row)
    for fine,coarse in [(12.5,25.),(6.25,12.5)]:
        a=h[h.dx_m==fine]; b=h[h.dx_m==coarse]; t=a.time_s.to_numpy(); qa=a.Q_1000_m3_s.to_numpy(); qb=b.Q_1000_m3_s.to_numpy()
        for shift in np.arange(-60,60.01,.5):
            shifted=np.interp(t-shift,t,qb,left=0,right=0)
            shifts.append(dict(pair=f'{fine:g}_vs_{coarse:g}',coarse_translation_s=shift,auxiliary_L1_relative=ratio(integral(abs(qa-shifted),t),integral(abs(qa),t))))
    save(timing,'section_timing_and_volume.csv'); sd=pd.DataFrame(shifts); save(sd,'auxiliary_shift_scan.csv'); best=sd.loc[sd.groupby('pair').auxiliary_L1_relative.idxmin()]; save(best,'auxiliary_best_shift.csv')
    stages=pd.read_csv(OUT/'phase_comparison.csv'); speeds=pd.read_csv(OUT/'velocity_momentum_timeseries.csv'); late=speeds[(speeds.pair=='12.5_vs_25')&(speeds.time_s==1800)].iloc[0]
    ep=[]
    for dx,g in spatial.groupby('dx_m'):
        ep.append(dict(dx_m=dx,final_energy_proxy=float(g.kinetic_energy_per_density_m5_s2.iloc[-1]),peak_energy_proxy=float(g.kinetic_energy_per_density_m5_s2.max()),final_to_peak_ratio=ratio(g.kinetic_energy_per_density_m5_s2.iloc[-1],g.kinetic_energy_per_density_m5_s2.max()),final_max_speed_m_s=float(g.max_abs_speed_m_s.iloc[-1])))
    save(ep,'stopping_evidence.csv')
    text=f'''# 第四问：截止前收敛补充验收

## 范围及执行

仅新增candidate真实地形6.25m参考情景一次。12.5m和25m直接读取带源码SHA256的既有缓存；输入逐项核对相同。候选源码SHA256为6892758960fde347f59756d0bdd772df9d84294a175be4f0334528b5807d1716。域、600000m³体积、100m宽、120s入口、3m入口深、μ=.1、ξ=300、1800s及CFL=.35不变。母剖面仍为同一corrected_z_m，6.25m只是其插值细化，不是新增DEM观测；端点延用同一母剖面边缘值。

6.25m实际格距6.249831m、3545格、11401步。输入600000m³、储存600000m³、域末流出0；相对质量残差约6.98e-15，流深非负，状态有限，最大CFL=.35。没有新求解器，没有修改参数、DEM、其他三问或final，没有推送GitHub。按verification-before-completion技能核对实际输出与派生计算；辅助计算测试单独保留。

## 一、阶段速度和动量

事先固定0–300s、300–900s、900–1800s窗口。名称分别为早期传播、中期流动检查窗、后期停止检查窗；实际强运动主要在早期，不能仅凭窗口名认定中期仍剧烈流动或后期完全停止。动能代理E/ρ=0.5 B∫hu²ds（m⁵/s²）时间序列另存。

各网格在同一输出时刻比较；较粗网格中心值线性插到细网格中心，沿用前轮误差口径。这是状态比较插值，不是新增数值解，也未用于重新积分求解。L1空间差包含实际dx。

- 速度绝对量：全域∫|Δu|ds、湿区并集(h任一>.001m)的平均绝对速度差及最大绝对差。
- 原始误差：保留全域未经速度筛选相对L1；另外原样保留前轮共同湿区(h两者>.05m)的相对L1。
- 活跃区域：共同湿区且任一速度绝对值>.1m/s，分子∫|Δu|、分母∫|u_fine|。取任一速度活跃避免把粗网格仍流动、细网格停下的差异简单筛掉；共同湿区之外的前缘差异仍由未筛选误差和动量反映。
- 单位宽动量q=hu(m²/s)直接用输出Q/B，比较全域∫|Δq|ds(m³/s)及相对L1，不施加活跃速度筛选。阶段相对误差是时空积分之比，不是各时刻百分比的平均。零分母标缺失，并保存支持区域长度。

12.5m对25m：早期/中期/后期湿区速度平均绝对差约0.955/0.0819/0.0178m/s；活跃速度相对差12.85%/18.26%/32.58%；动量相对L1约12.20%/28.87%/271.02%。后期高百分比不能隐藏，配套动量绝对L1阶段平均约66.98m³/s。

1800s原共同湿区速度误差仍是60.84%；该区域细网格平均速度仅{late.fine_commonwet_mean_speed_m_s:.6f}m/s，全湿区并集速度平均绝对差{late.velocity_wet_union_MAE_m_s:.6f}m/s，最大绝对差{late.velocity_max_abs_error_m_s:.5f}m/s，活跃共同湿区长度为0，因此活跃相对量缺失。该60.84%反映残余小速度不一致，作为高速传播精度判据已不合适，但不能删除或改写为通过。原始全域未筛选相对误差仍约15.26%。三网格最终动能代理仅为各自峰值约2.7e-7至3.5e-7，支持“接近停止”；局部最高速度仍有约0.12–0.17m/s，不能写成全域严格静止。

6.25m对12.5m：早期/中期活跃速度相对差降至8.77%/13.58%；动量相对差降至5.78%/19.92%；有改善但仍非整体达标。最大绝对速度差在前沿/入口附近仍敏感；不能以晚期小速度解释全部传播误差。

## 二、1000m过程线：时移、幅度与形状

| 网格(m) | 峰值Q(m³/s) | 最大值首次时刻(s) | ∫Qdt(m³) | 99%峰值平台(s) |
|---|---:|---:|---:|---|
|25|4991.870|120|610880.661|110–160|
|12.5|4997.443|150|614772.384|100–160|
|6.25|4999.507|155|614180.154|95–165|

时刻为相对假设入沟时间，采样间隔5s，不是灾害北京时间。长平台上极小幅度差就会改变argmax，因此120→150→155s不能解释为稳健的实际洪峰到达时间收敛。

12.5与25m原时间轴L1差16.08%；峰值幅度差仅0.1115%，积分体积差0.633%。按最大值时刻对齐反而使差异变成64.67%，再归一峰高约64.72%，证明“峰值对齐”在此平台波形上会失真。

为诊断时移，额外保留[-60,60]s、0.5s间隔的平移扫描（只作用于后处理曲线，绝不改预报/模型时间）。25m曲线平移-10s后辅助L1最小约7.79%，说明约一半原始差异可由整体时移解释，其余主要是上升沿展宽、退水段变化；幅度贡献很小。此分解顺序依赖、非唯一，最优平移是事后辅助诊断，不能替代原轴验收。流量时间质心25/12.5/6.25m为约192.37/176.15/168.81s，仍有时间过程网格依赖。

6.25与12.5m原轴差降至9.03%；幅度差0.0413%、积分量差0.0964%。按最大值对齐仍有17.06%，辅助最佳平移为-5s后约4.96%。这显示过程差减小，但未证明原轴过程线达到5%筛查要求，也不能拿对齐后低误差宣称预测通过。

**体积口径特别说明：** 上表是插值物理流量Bhu的梯形积分，不是有限体积界面数值通量的守恒积分。它超过600000m³源体积，不能作为可信的通过总物质量。根据最近1000m格面下游存量变化加域末净流出的守恒账，25/12.5/6.25m净通过量约596060/597866/597196m³；对应格面约999.13/999.69/999.97m，位置略有不同。物理Q积分与数值界面账约2.5–2.8%的差异需保留，不能把它说成质量凭空产生或混同两个口径。断面空间插值、5s采样积分和物理/数值通量差的贡献尚未分离。全域质量守恒通过不保证插值断面Q积分准确。

## 三、最细网格对照

| 指标 |12.5对25m|6.25对12.5m|判断|
|---|---:|---:|---|
|最大前锋相对差|0.289%|0.544%|绝对差均约一格以内，但未单调缩小|
|1800s流深L1|1.159%|1.238%|均较小，未继续下降|
|95%域内体积位置|0.0397%|0.0061%|继续改善|
|体积质心|0.228%|0.0703%|继续改善|
|峰值速度|7.863%|13.352%|变差|
|最终动量L1相对差|46.59%|23.05%|下降，但停止附近分母小|
|最终动量L1绝对差(m³/s)|4.287|1.777|下降|
|1000m原轴过程线L1|16.08%|9.03%|改善但未达5%|

三档前锋约1810.92/1805.69/1815.58m（25/12.5/6.25m）。这是同一地形与假设下的计算范围，不是实际灾害停积距离。状态相似不能证明未知DEM、入口或摩阻正确。

## 四、验收A–E与截止前采用方案

**A 最终空间状态：有条件支持数值稳定/一致性，尚无严格全指标单调收敛证明。** 质心和累计体积位置改善，最终流深约1.2%差，前锋差低于0.6%；适合展示空间情景。前锋及深度逐级差没有继续下降，不能用“已全面收敛”表述。

**B 活跃传播过程：尚未通过。** 早中期速度/动量改善有限，峰值速度加密反而增差，需继续标未验证。本轮到此停止优化，不开发格式、不调整参数。

**C 断面流量/到达时间：不能用于真实灾害定量解释。** 可以给出明确标注网格敏感性的情景数值和三网格对照；不能当作可靠洪峰、通量或真实提前量。平台argmax不稳健，时序尚未收敛，Bhu积分还不等于守恒界面量。

**D 探索性图表：候选值得保留。** 截止前推荐使用固定SHA的candidate、12.5m真实床面情景作为展示主版本，配6.25/25m对照；选择12.5m基于计算成本和三网格最终空间接近，不是因其更接近报道。展示模型方程、静摩擦平衡标准试验、质量收支、最终流深/体积位置及带网格对照的动态过程。不替换旧final；图注写明“未校准的入沟后单层一维探索性模拟；传播过程未全面收敛”。

本目录acceptance_supplement.png可直接作为三网格候选图；velocity_and_peak_alignment.png用于数值局限讨论。候选算法公式及标准测试材料见algorithm_validation/stage_report.md。旧final动画对应旧求解器，不能与candidate的新数值混用而不注明版本。

**E 持续未验证：** 绝对传播距离、真实流速/流深、洪峰时刻及流量、实际边界/物源/摩阻、DEM垂直基准与真实沟床代表性、侵蚀挟沙/相变/侧向传播；模拟流深不能写成沉积厚度。所有时钟仍是入沟相对时间；严禁用22km或10:59作本轮参数目标。

## 文件及复现

运行`python scripts/supplement_question4_acceptance.py`生成补充数据（已存在时使用本目录代码/输入指纹匹配的6.25m缓存），再运行`python scripts/write_question4_acceptance_report.py`生成本报告和辅助时移表。复核测试`python -m unittest tests.test_question4_acceptance_metrics -v`。

`acceptance_protocol.json`保留预定窗口、阈值和参数；`run_provenance.json`记录源码/床面指纹及三个状态来源；`velocity_momentum_timeseries.csv`保留原始失败项和分母；`phase_comparison.csv`为阶段汇总；`section_1000_comparison.csv`及`section_timing_and_volume.csv`为断面结果；`refinement_comparison.csv`为逐级对照。完整状态仍在各自独立缓存，旧final和源码只读。
'''
    (OUT/'acceptance_report.md').write_text(text,encoding='utf-8')
    (OUT/'README.md').write_text('# 第四问补充验收\n先读acceptance_report.md；图看acceptance_supplement.png和velocity_and_peak_alignment.png。\n仅新增固定candidate的6.25m真实床面实验。最终空间状态有条件稳定，传播过程与断面定量验收未通过；按要求停止继续优化。\n',encoding='utf-8')
    print(pd.DataFrame(timing).to_string(index=False)); print(best.to_string(index=False)); print(pd.DataFrame(ep).to_string(index=False))

if __name__=='__main__': main()
