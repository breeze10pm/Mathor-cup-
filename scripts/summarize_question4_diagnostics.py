"""Summarize completed diagnostic runs without rerunning or tuning the model."""
from diagnose_question4_convergence import OUT, ROOT, original, save, sha
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from question4_visuals import save_map, save_multi_panel

def main():
    e=pd.read_csv(OUT/'convergence_experiments.csv')
    f=pd.read_csv(OUT/'front_definition_sensitivity.csv')
    a=pd.read_csv(OUT/'terrain_anomalies.csv')
    p=pd.read_csv(OUT/'common_bed_profile.csv')
    summary=f.groupby(['case','threshold_m'],as_index=False).front_m.max()
    save(summary,'front_threshold_summary.csv')
    differences=e[e.terrain=='legacy'].merge(e[e.terrain=='pixel_corrected'],on=['requested_dx_m','cfl'],suffixes=('_before','_after'))
    differences['front_change_m']=differences.front_max_m_after-differences.front_max_m_before
    save(differences,'before_after_comparison.csv')
    top=a[(a.version=='legacy')&(a.requested_dx_m==100)].copy()
    top=top.loc[top.delta_z_m.abs().sort_values(ascending=False).index].head(10)
    save(top,'largest_terrain_jumps.csv')
    save_map(OUT/'terrain_anomaly_locations.png',extent_geometries=[],route_geometries=[LineString(p[['x_utm45','y_utm45']].values)],simulated_geometries={},points={f'{i+1}: {r.distance_m/1000:.2f}km':(r.x_utm45,r.y_utm45) for i,r in enumerate(top.itertuples())},title='Largest original 100 m bed jumps; EPSG:32645; no inferred corrections')
    flux_rows=[]; profiles=[]
    for dx in [12.5,25,50,100,200]:
        d=np.load(OUT/f'flat_{dx:g}_0.35.npz')
        for tt in [120,300,600,1800]:
            i=np.argmin(abs(d['times_s']-tt)); h=d['depth_m'][i]; q=d['discharge_m3_s'][i]/100
            flux=original._interface_fluxes(h,q,d['bed_m'],h[0],0)[0]*100
            flux_rows.append(dict(dx_m=dx,time_s=float(d['times_s'][i]),max_physical_abs_Q_m3_s=float(abs(q*100).max()),max_interior_numerical_mass_flux_m3_s=float(abs(flux[1:-1]).max()),wet_cells=int((h>.001).sum())))
        for i,t in enumerate(d['times_s']):
            profiles.append(dict(dx_m=dx,time_s=t,front_m=d['front_position_m'][i],max_abs_Q_m3_s=abs(d['discharge_m3_s'][i]).max()))
    save(pd.DataFrame(flux_rows),'interface_flux_diagnostics.csv')
    save(pd.DataFrame(profiles),'flat_spurious_creep.csv')
    panels=[]
    for terrain in ['flat','legacy']:
        series=[]
        for dx,col in zip([12.5,25,50,100,200],['#2563eb','#dc2626','#16a34a','#9333ea','#b45309']):
            d=np.load(OUT/f'{terrain}_{dx:g}_0.35.npz'); series.append((str(dx)+'m',d['times_s']/60,d['front_position_m']/1000,col))
        panels.append(dict(title=terrain+' front evolution (h>0.001m)',x_label='time (min)',y_label='front (km)',series=series))
    save_multi_panel(OUT/'front_evolution.png',panels,size=(1600,800))
    # Quantify prescribed-boundary momentum inconsistency without changing solver.
    qin=50.; hin=3.; expected=qin**2/hin+.5*original.GRAVITY_M_S2*hin**2
    boundary=[]
    for h0 in [0.,3.,6.,12.]:
        hh=np.array([h0,0.,0.]); qq=np.zeros(3)
        fh,fl,fr,*_=original._interface_fluxes(hh,qq,np.zeros(3),hin,qin)
        boundary.append(dict(interior_h_m=h0,imposed_mass_flux_m2_s=fh[0],momentum_flux_used_m3_s2=fr[0],fully_prescribed_supercritical_flux_m3_s2=expected,relative_difference=(fr[0]-expected)/expected))
    save(pd.DataFrame(boundary),'inlet_momentum_check.csv')
    data=e[(e.cfl==.35)].pivot(index='requested_dx_m',columns='terrain',values='front_max_m')
    table=data.round(2).to_csv()
    report=f'''# 第四问网格收敛诊断与最小修复

## 结论
35组隔离实验全部实际完成；原始四问结果未覆盖。15项Q4单元/图形/新回归测试通过，但真实场景及标准床面并未通过本次预设的整体收敛验收。不能把单元测试通过写成网格收敛。

1. **求解器是否存在错误？** 确认输入取样层存在像元索引错误（角点坐标rint），修复为floor。修复前新增2例为1失败1错误，修复后连同旧测试15例全部通过。核心HLL/水静力公式没有发现简单符号错误，但平坦床面的摩擦静止状态无法保持：动量被摩擦截停后HLL质量通量仍扩散流深。`interface_flux_diagnostics.csv`直接比较数值质量通量与Bhu；这说明仅保持静水配平并不足以保持摩擦支撑的静止堆体。入口强制质量但未强制相应动量也是边界定义不一致，见独立探针表。未在缺少验证时改写主通量或摩擦平衡格式。
2. **地形是否主要原因？** 不能归因为地形。平坦床面也有严重网格依赖；高程台阶和陡坡进一步引入水静力重构截断。仅修复像元索引后仍不收敛。没有证据把逆坡自动认定DEM错误，也没有对其削峰/平滑。
3. **可信收敛趋势？** 未获得满足多指标要求的可信趋势。加到12.5m揭示更多差异；恒坡25/50m前锋接近也不代表深度/速度/过程线收敛。
4. **仍不收敛指标？** 前锋、流深分布、峰值速度和有效断面流量过程。固定时刻湿区速度或流量全零的条目保留缺失，视为无信息而非通过。详见field_convergence.csv。质量误差与非负性通过仅说明离散守恒/数值稳定。
5. **可用结论？** 可展示给定假设下质量动量模型、参数实验和数值失败诊断；不能定量断言实际传播距离、流深、速度、到达时间或堆积量。前锋不等于实体颗粒边界。
6. **能否冻结？** 可以作为“明确揭示未收敛的探索性动力学与诊断版本”存档/有条件提交；不能标为通过数值可靠性验收。继续定量研究需采用并验证摩擦平衡/低扩散格式与一致入口条件，属于下一项方法改进。

## 实验定义和真实结果
所有实验用同一22.155652km域、600000m³、100m宽、120s矩形入流、3m入口、mu=.1、xi=300、1800s；标准床面 z=0、z=-.15s、z=-.03s+20sin(2πs/2000)，单位m。网格因固定终点略小于标称值，实际dx在CSV中。CFL=.35；50m另比.1/.2。输出每5s同步，会截短部分时间步，故CFL试验结论仅在此输出节奏下成立。
前锋最大距离(m)：
```csv
{table}
```
完整h/u/Q数组保存为各实验NPZ；300/600/1200/1800s空间L1和500/1000/2000m过程线比较见field_convergence.csv。速度仅比较两网格均h>.05m区域；固定物理断面用Bhu插值，非数值界面质量通量。二者差异另有接口探针。缺少解析真解，不宣称误差阶或Richardson外推准确率。

## 地形与空间证据
共同母剖面common_bed_profile.csv包括原始/修正高程、差值、链程和EPSG:32645坐标；input_provenance.json含DEM SHA256、CRS与采样定义。原始/修正端到端落差分别{p.original_z_m.iloc[0]-p.original_z_m.iloc[-1]:.3f}/{p.corrected_z_m.iloc[0]-p.corrected_z_m.iloc[-1]:.3f}m；最大索引修正高程差{abs(p.delta_z_m).max():.3f}m。未混用其他垂直基准DEM；高程基准仍未知。12.5m两端延用原25m母剖面端值，不是新测地形，边缘各不足12.5m。
原100m最大跃变位于距入口{top.iloc[0].distance_m:.3f}m，EPSG:32645 ({top.iloc[0].x_utm45:.3f}, {top.iloc[0].y_utm45:.3f})，高程从{top.iloc[0].previous_z_m:.3f}到{top.iloc[0].z_m:.3f}m。所有逆坡/大跳变坐标见terrain_anomalies.csv；10处最大跃变见独立位置图。原报告18.5%是单元中心梯度为逆坡的比例，与相邻高程差计数不同。源栅格文件名含fillAW3D30，但无镶嵌掩膜，无法判定某跃变为接缝。现有中心线和DEM不足以独立确定山坡/山脊误采样，故未改线或删除地形。

## 质量、CFL和前锋定义
全部实验入流约600000m³、下游流出0、域内储存约600000m³，最大绝对质量残差{e.mass_residual_m3.abs().max():.3g}m³，相对误差最大{e.mass_relative_error.max():.3g}。零流出不是漏列，前锋未达出口；原代码用max(outlet,0)对允许回流的情景不完整，本次无回流并未触发该问题。状态有限且非负。
front_definition_sensitivity.csv包含每5s的.001/.01/.05m末湿单元位置，不改变求解器干床容差；因此这是观测指标敏感性，不是数值干湿算法改造。阈值结果见front_threshold_summary.csv。最大前锋依赖微薄单元并有约半格定位误差；提高阈值不自动修复扩散。

## 最小修复及未修改部分
只修复sample_raster_nearest的索引；原模块完整副本在本目录，独立诊断脚本使用该副本进行动量算法对照。pixel_corrected实验只换母剖面索引，两组其他条件完全一致。before_after_comparison.csv保留结果；无需改摩阻、体积、宽度或报道时间。未强行抑制HLL扩散通量，因为直接把静止单元质量通量置零会破坏真实溃坝/启动过程，需要专门的摩擦平衡格式验证。
水静力重构在坡度、网格尺度和流深某些组合下有已知局限：Delestre et al. (2012), DOI 10.1016/j.crma.2012.08.004，https://comptes-rendus.academie-sciences.fr/mathematique/item/10.1016/j.crma.2012.08.004.pdf 。该文支持机制可能性，不等于已经证明本项目全部误差来源。

## 运行与测试
在mc-base正确激活（Library/bin、PROJ_DATA、GDAL_DATA）后运行python scripts/diagnose_question4_convergence.py及python scripts/summarize_question4_diagnostics.py。首次未激活GIS运行环境的进程异常结束，没有形成结果；激活后35组全部完成。测试命令：python -m unittest tests.test_question4_dynamics tests.test_question4_diagnostic_fixes tests.test_question4_visuals -v。完整前后日志随目录保存。不下载数据，不覆盖final，不修改其他三问；原final和B/C资料包仍对应旧版本。
'''
    (OUT/'diagnosis_report.md').write_text(report,encoding='utf-8')
    (OUT/'README.md').write_text('# Q4诊断入口\n先读diagnosis_report.md，再看convergence_diagnostics.png与terrain_profile_diagnostics.png。逐次结果在convergence_experiments.csv；完整状态在NPZ，可由独立入口重算。质量守恒通过，整体收敛未通过。',encoding='utf-8')

if __name__=='__main__': main()
