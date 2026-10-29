"""Legacy diagnostics, or explicit versioned runs using --solver selection."""
import sys
if __name__ == '__main__' and '--solver' in sys.argv:
    from run_question4_algorithm_validation import main as selected_main
    selected_main()
    raise SystemExit(0)
from pathlib import Path
import json, hashlib, shutil, importlib.util, sys
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from question4_visuals import save_multi_panel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/question4/convergence_diagnostics'
OUT.mkdir(parents=True, exist_ok=True)
snapshot = OUT/'question4_dynamics_original.py'
if not snapshot.exists():
    shutil.copy2(ROOT/'scripts/question4_dynamics_v1_reference.py', snapshot)
spec=importlib.util.spec_from_file_location('q4original',snapshot)
original=importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
cfg=json.loads((ROOT/'config/question4-simulation.json').read_text(encoding='utf-8'))
center=pd.read_csv(ROOT/cfg['model']['centerline_csv'])
event=json.loads((ROOT/cfg['model']['event_context_summary']).read_text(encoding='utf-8'))
route=event['route_candidates'][0]
start=route['source_chainage_km']*1000; end=route['port_chainage_km']*1000; length=end-start
grid=np.array([12.5,25,50,100,200])
base=dict(width_m=100.,volume_m3=600000.,pulse_duration_s=120.,inlet_depth_m=3.,mu=.1,xi_m_s2=300.,end_time_s=1800.,output_interval_s=5.)

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def save(df,name): df.to_csv(OUT/name,index=False,encoding='utf-8-sig')

def main():
    # Fixed 25 m master sampling locations reproduce v1; corrected pixel indexing
    # changes only raster coordinate convention, never removes terrain features.
    s,_=original.prepare_uniform_profile(dict(chainage_m=center.chainage_m,elev_m=center.elev_m),start,end,25.)
    xx=np.interp(s,center.chainage_m,center.x_utm45); yy=np.interp(s,center.chainage_m,center.y_utm45)
    dempath=ROOT/cfg['model']['input_dem']
    with rasterio.open(dempath) as ds:
        a=ds.read(1); tr=ds.transform
        old,_=original.sample_raster_nearest(a,tr,xx,yy,'EPSG:32645',str(ds.crs),ds.nodata)
        rx,ry=Transformer.from_crs('EPSG:32645',ds.crs,always_xy=True).transform(xx,yy)
        rows,cols=rasterio.transform.rowcol(tr,rx,ry)
        corrected=a[rows,cols].astype(float)
        if not np.isfinite(corrected).all() or np.any(corrected==0) or np.any(corrected==ds.nodata): raise ValueError('Invalid sample; no filling permitted')
        metadata={'dem':cfg['model']['input_dem'],'sha256':sha(dempath),'raster_crs':str(ds.crs),'profile_crs':'EPSG:32645','vertical_datum':'unknown; no DEM mixing','sampling':'fixed original ~25m chainages; legacy rint vs corrected floor pixel index','transform':list(tr),'base_parameters':base,'domain_start_chainage_m':start,'domain_end_chainage_m':end,'solver_original_sha256':sha(snapshot)}
    master=pd.DataFrame(dict(chainage_m=s,distance_m=s-start,x_utm45=xx,y_utm45=yy,original_z_m=old,corrected_z_m=corrected,delta_z_m=corrected-old))
    provenance=OUT/'input_provenance.json'
    if provenance.exists() and json.loads(provenance.read_text(encoding='utf-8')) != metadata:
        raise RuntimeError('Inputs/config changed: use a new diagnostic output directory; stale cache reuse refused')
    save(master,'common_bed_profile.csv'); provenance.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    beds=[]; anomalies=[]
    for version,z in [('legacy',old),('pixel_corrected',corrected)]:
        for dx in grid:
            n=int(np.ceil(length/dx)); x=(np.arange(n)+.5)*length/n
            bed=np.interp(x+start,s,z)
            for i in range(n):
                beds.append(dict(version=version,requested_dx_m=dx,distance_m=x[i],z_m=bed[i],x_utm45=np.interp(x[i]+start,center.chainage_m,center.x_utm45),y_utm45=np.interp(x[i]+start,center.chainage_m,center.y_utm45)))
                if i and (bed[i]>bed[i-1] or abs(bed[i]-bed[i-1])/(x[i]-x[i-1])>.5):
                    anomalies.append({**beds[-1],'previous_z_m':bed[i-1],'delta_z_m':bed[i]-bed[i-1],'grade':(bed[i]-bed[i-1])/(x[i]-x[i-1]),'reason':'uphill or abs grade >0.5; not automatically an error','source':cfg['model']['input_dem']})
    save(pd.DataFrame(beds),'terrain_profile_comparison.csv'); save(pd.DataFrame(anomalies),'terrain_anomalies.csv')
    (OUT/'phase1_readonly_diagnosis.md').write_text('''# 只读诊断（修改前）
旧版收敛各网格共用600000 m³、100 m宽、120 s矩形入流、3 m入口、mu=.1、xi=300和1800 s，同一A入口和口岸终点。旧版25 m采样剖面固定，但各计算网格取中心值，不能解析相同短波地形；12.5 m端点位于母剖面外，np.interp常值延伸不足12.5 m，明确保留作旧版定义。
像元角点索引使用rint而非floor，非整数像元位置会错取右/下邻格；并非DEM实测错误。修正仅换取样索引。
HLL水静力侧修正符号符合静水配平；大于流深的床面台阶会截断重构流深。粗网格薄层、大坡度可有严重截断/扩散，须用理想床面隔离。
入口只覆盖质量通量，动量来自黎曼求解，指定Q和h不构成一致的强制动量通量。下游质量账取max(Fh,0)，若发生回流则漏记；本次须核查实算残差与总量。
前锋取h>0.001 m的最末单元中心，与网格、薄层扩散有关；速度为该单元流速，非前锋位移速度。
Voellmy分裂中的干层1/h及Coulomb截断可能与时间步耦合；保持算法先做CFL实验。
检验预注册：同一物理域/参数/1800s。12.5/25/50/100/200m；比较逐级前锋差、固定300/600/1200/1800s的深度与湿区速度L1、500/1000/2000m断面流量L1。误差相对最细网格仅为自收敛证据，非真实解误差。需逐级差缩小并且最后一级相对量<5%，且深度、湿区速度、流量各项一致才称本实验可信趋势。5%为预设工程筛查，非真实性证明。若有全零断面标无信息，不算通过。禁止以参数调整制造收敛。
''',encoding='utf-8')
    experiments=[]; fronts=[]; hydro=[]; results={}
    cases=[(terrain,float(dx),.35) for terrain in ['flat','slope','smooth','legacy','pixel_corrected'] for dx in grid]
    cases += [(terrain,50.,cfl) for terrain in ['flat','slope','smooth','legacy','pixel_corrected'] for cfl in [.1,.2]]
    for terrain,dx,cfl in cases:
        tag=f'{terrain}_{dx:g}_{cfl:g}'
        n=int(np.ceil(length/dx)); x=(np.arange(n)+.5)*length/n
        if terrain=='flat': bed=np.zeros(n)
        elif terrain=='slope': bed=-.15*x
        elif terrain=='smooth': bed=-.03*x+20*np.sin(2*np.pi*x/2000)
        else: bed=np.interp(x+start,s,old if terrain=='legacy' else corrected)
        cache=OUT/(tag+'.npz')
        try:
            if cache.exists():
                d=np.load(cache); result={k:d[k] for k in d.files}
            else:
                result=original.run_simulation(x_m=x,bed_m=bed,cfl=cfl,**base)
                np.savez_compressed(cache,**{k:v for k,v in result.items() if k!='mass_balance_columns'})
            results[tag]=result
            h=result['depth_m']; u=result['velocity_m_s']; t=result['times_s']
            row=dict(case=tag,terrain=terrain,requested_dx_m=dx,actual_dx_m=length/n,cfl=cfl,status='completed',front_max_m=float(result['max_front_position_m']),peak_speed_m_s=float(abs(u).max()),min_depth_m=float(h.min()),injected_m3=float(result['injected_volume_m3']),stored_m3=float(result['final_mass_m3']),outlet_m3=float(result['outlet_volume_m3']),mass_residual_m3=float(result['final_mass_m3']-result['injected_volume_m3']+result['outlet_volume_m3']),mass_relative_error=float(result['relative_mass_error']),max_cfl=float(result['max_cfl_number']),hr_step_exceeds_3m_fraction=float(np.mean(abs(np.diff(bed))>3)))
            experiments.append(row)
            for threshold in [.001,.01,.05]:
                fp=np.array([x[np.flatnonzero(hh>threshold)[-1]] if (hh>threshold).any() else 0 for hh in h])
                for ti,fi in zip(t,fp): fronts.append(dict(case=tag,threshold_m=threshold,time_s=ti,front_m=fi))
            for section in [500,1000,2000]:
                for i,ti in enumerate(t): hydro.append(dict(case=tag,section_m=section,time_s=ti,Q_m3_s=np.interp(section,x,result['discharge_m3_s'][i])))
            print(tag,round(row['front_max_m'],2),flush=True)
        except Exception as exc:
            experiments.append(dict(case=tag,terrain=terrain,requested_dx_m=dx,cfl=cfl,status=repr(exc))); print(tag,repr(exc),flush=True)
        save(pd.DataFrame(experiments),'convergence_experiments.csv')
    df=pd.DataFrame(experiments); save(pd.DataFrame(fronts),'front_definition_sensitivity.csv'); save(pd.DataFrame(hydro),'cross_section_hydrographs.csv')
    save(df[df.requested_dx_m==50],'cfl_sensitivity.csv')
    errors=[]
    for terrain in ['flat','slope','smooth','legacy','pixel_corrected']:
        for fine,coarse in [(12.5,25),(25,50),(50,100),(100,200)]:
            a=results[f'{terrain}_{fine:g}_0.35']; b=results[f'{terrain}_{coarse:g}_0.35']
            x=a['cell_center_m']; xb=b['cell_center_m']
            for tt in [300,600,1200,1800]:
                i=int(np.argmin(abs(a['times_s']-tt))); j=int(np.argmin(abs(b['times_s']-tt)))
                for field in ['depth_m','velocity_m_s']:
                    av=a[field][i]; bv=np.interp(x,xb,b[field][j]); mask=(a['depth_m'][i]>.05)&(np.interp(x,xb,b['depth_m'][j])>.05) if field=='velocity_m_s' else np.ones(len(x),bool)
                    denom=np.sum(abs(av[mask])); errors.append(dict(terrain=terrain,fine_dx=fine,coarse_dx=coarse,time_s=tt,metric=field,relative_L1=np.sum(abs(av[mask]-bv[mask]))/denom if denom>0 else np.nan))
            for section in [500,1000,2000]:
                av=np.array([np.interp(section,x,q) for q in a['discharge_m3_s']]); bv=np.array([np.interp(section,xb,q) for q in b['discharge_m3_s']]); den=np.sum(abs(av))
                errors.append(dict(terrain=terrain,fine_dx=fine,coarse_dx=coarse,time_s=1800,metric=f'Q_{section}m',relative_L1=np.sum(abs(av-bv))/den if den>0 else np.nan))
    save(pd.DataFrame(errors),'field_convergence.csv')
    colors=['#2563eb','#dc2626','#16a34a','#9333ea','#b45309']
    panels=[]
    for terrain in ['flat','slope','smooth','legacy','pixel_corrected']:
        d=df[(df.terrain==terrain)&(df.cfl==.35)].sort_values('requested_dx_m')
        panels.append(dict(title=terrain+' (fixed parameters)',x_label='requested dx (m)',y_label='max front (m)',series=[('h>0.001m',d.requested_dx_m,d.front_max_m,'#2563eb')]))
    save_multi_panel(OUT/'convergence_diagnostics.png',panels,size=(1800,1800))
    save_multi_panel(OUT/'terrain_profile_diagnostics.png',[
        dict(title='Fixed master profile; no smoothing',x_label='distance (km)',y_label='elevation (m)',series=[('original',(s-start)/1000,old,colors[0]),('pixel corrected',(s-start)/1000,corrected,colors[1])]),
        dict(title='Pixel index correction only',x_label='distance (km)',y_label='corrected minus original (m)',series=[('delta',(s-start)/1000,corrected-old,colors[1])]),
        dict(title='Centerline coordinates EPSG:32645',x_label='Easting (m)',y_label='Northing (m)',series=[('route',xx,yy,colors[0])]),
        dict(title='Master intersample elevation change',x_label='distance (km)',y_label='delta z (m)',series=[('original',(s[1:]-start)/1000,np.diff(old),colors[0])])],size=(1800,1200))
    print('DIAGNOSTICS COMPLETED',flush=True)

if __name__=='__main__': main()
