"""One additional 6.25 m run; postprocessing only, no solver/physics edits."""
from pathlib import Path
import json,hashlib,datetime,sys
import numpy as np
import pandas as pd
from q4_solver_registry import execute,manifest
from question4_visuals import save_multi_panel

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/question4/convergence_supplement'
SOURCE=ROOT/'scripts/question4_friction_candidate.py'
PHASES=[('early',0,300),('active_window',300,900),('late_stopping_check',900,1800)]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(rows,name): pd.DataFrame(rows).to_csv(OUT/name,index=False,encoding='utf-8-sig')
def ratio(n,d): return float(n/d) if abs(d)>1e-12 else np.nan
def integral(y,t): return float(np.trapezoid(y,t))
def load(p):
    with np.load(p,allow_pickle=False) as d: return {k:d[k] for k in d.files}

def hydro_compare(t,a,b):
    ia=int(np.argmax(a)); ib=int(np.argmax(b)); shift=float(t[ia]-t[ib])
    # Auxiliary shape diagnostic: zero padding outside recorded horizon only.
    aligned=np.interp(t-shift,t,b,left=0,right=0)
    normalized=aligned*ratio(a[ia],b[ib])
    den=integral(abs(a),t)
    return dict(fine_peak_m3_s=float(a[ia]),coarse_peak_m3_s=float(b[ib]),fine_peak_time_s=float(t[ia]),coarse_peak_time_s=float(t[ib]),coarse_peak_delay_s=-shift,fine_net_volume_m3=integral(a,t),coarse_net_volume_m3=integral(b,t),fine_positive_volume_m3=integral(np.maximum(a,0),t),coarse_positive_volume_m3=integral(np.maximum(b,0),t),raw_L1_relative=ratio(integral(abs(a-b),t),den),peak_aligned_L1_relative=ratio(integral(abs(a-aligned),t),den),aligned_peak_normalized_L1_relative=ratio(integral(abs(a-normalized),t),den),peak_relative_difference=ratio(abs(a[ia]-b[ib]),abs(a[ia])),volume_relative_difference=ratio(abs(integral(a-b,t)),abs(integral(a,t)))),aligned,normalized

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    code_sha=sha(SOURCE)
    gate=json.loads((ROOT/'output/question4/algorithm_validation/standard_gate.json').read_text(encoding='utf-8'))
    if not gate['passed'] or gate['solver_sha256']!=code_sha: raise RuntimeError('Candidate differs from tested version')
    idx=pd.read_csv(ROOT/'output/question4/algorithm_validation/run_index.csv')
    states={}; sources={}; old_meta={}
    for dx in [12.5,25.]:
        row=idx[(idx.solver=='candidate')&(idx.case==f'real_{dx:g}_1800')].iloc[0]
        path=ROOT/row.path
        meta=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
        if meta['solver_sha256']!=code_sha: raise RuntimeError('Old state code mismatch')
        states[dx]=load(path/'state.npz'); sources[str(dx)]=path.relative_to(ROOT).as_posix(); old_meta[dx]=meta
    # Same parameters/domain as the cached reference; no independent redefinition.
    parameters={k:v for k,v in old_meta[12.5]['inputs'].items() if k not in ['x_m','bed_m']}
    if parameters!={k:v for k,v in old_meta[25.]['inputs'].items() if k not in ['x_m','bed_m']}: raise RuntimeError('Reference parameters differ')
    ref=states[12.5]; length=float(ref['cell_width_m'])*len(ref['cell_center_m'])
    profile_path=ROOT/'output/question4/convergence_diagnostics/common_bed_profile.csv'
    profile=pd.read_csv(profile_path)
    for dx in [12.5,25.]:
        # Demonstrate the current common profile reproduces the cached inputs.
        z=np.interp(states[dx]['cell_center_m'],profile.distance_m,profile.corrected_z_m)
        if not np.array_equal(z,states[dx]['bed_m']): raise RuntimeError('Common bed differs from cached bed')
    n=int(np.ceil(length/6.25)); x=(np.arange(n)+.5)*length/n
    kwargs=dict(parameters,x_m=x,bed_m=np.interp(x,profile.distance_m,profile.corrected_z_m))
    (OUT/'acceptance_protocol.json').write_text(json.dumps(dict(phases=PHASES,active_h_m=.05,active_speed_m_s=.1,raw_wet_h_m=.001,section_m=1000,output_dt_s=5,screen_relative=.05,solver_sha256=code_sha,parameters=parameters,common_bed_sha256=sha(profile_path),comparison='coarse cell centers linearly interpolated to fine cell centers; same convention as preceding acceptance',late_window='not assumed stationary; diagnose actual speed/energy'),indent=2),encoding='utf-8')
    new,path=execute(SOURCE,kwargs,OUT/'cache','candidate')
    states[6.25]=new; sources['6.25']=path.relative_to(ROOT).as_posix()
    snapshots=[]; grids=[]; hydro_rows=[]; traces={}
    for dx,r in states.items():
        xx=r['cell_center_m']; cell=float(r['cell_width_m']); B=float(r['channel_width_m']); h=r['depth_m']; u=r['velocity_m_s']; tt=r['times_s']
        discharge=np.array([np.interp(1000,xx,v) for v in r['discharge_m3_s']]); traces[dx]=discharge
        # Exact mass ledger downstream of nearest grid face (not Bhu integration).
        face_index=int(round(1000/cell)); face_x=face_index*cell
        bal=r['mass_balance']; out_t=np.r_[0,bal[:,0]]; out_v=np.r_[0,bal[:,3]]
        cumulative_face=B*cell*(h[:,face_index:].sum(axis=1)-h[0,face_index:].sum())+np.interp(tt,out_t,out_v)
        for i,t in enumerate(tt):
            hydro_rows.append(dict(dx_m=dx,time_s=t,Q_1000_m3_s=discharge[i],nearest_face_m=face_x,net_face_volume_m3=cumulative_face[i]))
            mass=np.cumsum(h[i]); total=mass[-1]; edges=np.r_[0,xx+cell/2]
            row=dict(dx_m=dx,time_s=t,mass_centroid_m=ratio(np.dot(xx,h[i]),total),kinetic_energy_per_density_m5_s2=float(.5*B*cell*np.sum(h[i]*u[i]**2)),max_abs_speed_m_s=float(abs(u[i]).max()),storage_m3=float(total*B*cell))
            for fract in [.5,.95,.99]: row[f'mass_{fract:g}_position_m']=float(np.interp(fract*total,np.r_[0,mass],edges)) if total>0 else np.nan
            for th in [.001,.01,.05]:
                wet=np.flatnonzero(h[i]>th); row[f'front_{th:g}_m']=float(xx[wet[-1]]) if wet.size else 0.
            snapshots.append(row)
        grids.append(dict(dx_m=dx,actual_dx_m=cell,cells=len(xx),max_front_m=float(r['max_front_position_m']),peak_speed_m_s=float(abs(u).max()),mass_error=float(r['relative_mass_error']),min_h_m=float(h.min()),max_cfl=float(r['max_cfl_number']),final_storage_m3=float(r['final_mass_m3']),input_m3=float(r['injected_volume_m3']),outflow_m3=float(r['outlet_volume_m3']),steps=int(r['step_count']),final_numerical_volume_near1000_m3=float(cumulative_face[-1])))
    save(grids,'grid_summary.csv'); save(snapshots,'spatial_mass_timeseries.csv'); save(hydro_rows,'section_1000_timeseries.csv')
    samples=[]; stages=[]; comparisons=[]; hydrostats=[]; aligned_rows=[]
    snap=pd.DataFrame(snapshots)
    for fine,coarse in [(12.5,25.),(6.25,12.5),(6.25,25.)]:
        a=states[fine]; b=states[coarse]; x=a['cell_center_m']; xb=b['cell_center_m']; cell=float(a['cell_width_m']); t=a['times_s']
        if not np.array_equal(t,b['times_s']): raise RuntimeError('Time axes differ')
        pair=f'{fine:g}_vs_{coarse:g}'; local=[]
        for i,ti in enumerate(t):
            ha=a['depth_m'][i]; ua=a['velocity_m_s'][i]; hb=np.interp(x,xb,b['depth_m'][i]); ub=np.interp(x,xb,b['velocity_m_s'][i]); qa=a['discharge_m3_s'][i]/float(a['channel_width_m']); qb=np.interp(x,xb,b['discharge_m3_s'][i]/float(b['channel_width_m']))
            wet=(ha>.001)|(hb>.001); common=(ha>.05)&(hb>.05); active=common&(np.maximum(abs(ua),abs(ub))>.1)
            du=abs(ua-ub)
            row=dict(pair=pair,time_s=ti,velocity_abs_L1_m2_s=float(du.sum()*cell),velocity_wet_union_MAE_m_s=float(np.mean(du[wet])) if wet.any() else np.nan,velocity_max_abs_error_m_s=float(du.max()),raw_speed_numerator=float(du.sum()*cell),raw_speed_denominator=float(abs(ua).sum()*cell),raw_unfiltered_velocity_relative=ratio(du.sum(),abs(ua).sum()),raw_commonwet_numerator=float(du[common].sum()*cell),raw_commonwet_denominator=float(abs(ua[common]).sum()*cell),raw_commonwet_velocity_relative=ratio(du[common].sum(),abs(ua[common]).sum()),active_speed_numerator=float(du[active].sum()*cell),active_speed_denominator=float(abs(ua[active]).sum()*cell),active_velocity_relative=ratio(du[active].sum(),abs(ua[active]).sum()),active_length_m=float(active.sum()*cell),wet_union_length_m=float(wet.sum()*cell),fine_commonwet_mean_speed_m_s=float(abs(ua[common]).mean()) if common.any() else np.nan,momentum_abs_L1_m3_s=float(abs(qa-qb).sum()*cell),momentum_denominator_m3_s=float(abs(qa).sum()*cell),momentum_relative_L1=ratio(abs(qa-qb).sum(),abs(qa).sum()),depth_abs_L1_m2=float(abs(ha-hb).sum()*cell),depth_relative_L1=ratio(abs(ha-hb).sum(),abs(ha).sum()))
            local.append(row); samples.append(row)
        df=pd.DataFrame(local)
        for name,lo,hi in PHASES:
            v=df[df.time_s.between(lo,hi)]; ts=v.time_s.values
            stage=dict(pair=pair,phase=name,start_s=lo,end_s=hi,mean_velocity_abs_L1_m2_s=integral(v.velocity_abs_L1_m2_s,ts)/(hi-lo),mean_wet_union_MAE_m_s=float(v.velocity_wet_union_MAE_m_s.mean()),max_velocity_absolute_error_m_s=float(v.velocity_max_abs_error_m_s.max()),mean_active_length_m=integral(v.active_length_m,ts)/(hi-lo))
            for name2,num,den in [('raw_unfiltered_velocity_relative','raw_speed_numerator','raw_speed_denominator'),('original_commonwet_velocity_relative','raw_commonwet_numerator','raw_commonwet_denominator'),('active_velocity_relative','active_speed_numerator','active_speed_denominator'),('momentum_relative_L1','momentum_abs_L1_m3_s','momentum_denominator_m3_s')]: stage[name2]=ratio(integral(v[num],ts),integral(v[den],ts))
            stage['mean_momentum_abs_L1_m3_s']=integral(v.momentum_abs_L1_m3_s,ts)/(hi-lo); stages.append(stage)
        stats,aligned,normalized=hydro_compare(t,traces[fine],traces[coarse]); hydrostats.append(dict(pair=pair,**stats))
        for ti,aa,bb,cc,dd in zip(t,traces[fine],traces[coarse],aligned,normalized): aligned_rows.append(dict(pair=pair,time_s=ti,fine_Q=aa,coarse_Q=bb,peak_aligned_coarse_Q=cc,aligned_normalized_coarse_Q=dd))
        row=dict(pair=pair,max_front_relative=ratio(abs(float(a['max_front_position_m']-b['max_front_position_m'])),float(a['max_front_position_m'])),final_depth_relative=float(df.iloc[-1].depth_relative_L1),final_momentum_relative=float(df.iloc[-1].momentum_relative_L1),final_momentum_absolute_m3_s=float(df.iloc[-1].momentum_abs_L1_m3_s),peak_speed_relative=ratio(abs(abs(a['velocity_m_s']).max()-abs(b['velocity_m_s']).max()),abs(a['velocity_m_s']).max()))
        for key in ['mass_centroid_m','mass_0.95_position_m','mass_0.99_position_m']:
            av=float(snap[(snap.dx_m==fine)&(snap.time_s==1800)].iloc[0][key]); bv=float(snap[(snap.dx_m==coarse)&(snap.time_s==1800)].iloc[0][key]); row[key+'_relative']=ratio(abs(av-bv),abs(av))
        comparisons.append(row)
    for rows,name in [(samples,'velocity_momentum_timeseries.csv'),(stages,'phase_comparison.csv'),(comparisons,'refinement_comparison.csv'),(hydrostats,'section_1000_comparison.csv'),(aligned_rows,'section_1000_aligned.csv')]: save(rows,name)
    colors={6.25:'#dc2626',12.5:'#2563eb',25.:'#64748b'}
    save_multi_panel(OUT/'acceptance_supplement.png',[
        dict(title='1000 m section: original clock',x_label='relative time (s)',y_label='Q (m3/s)',series=[(f'{dx:g}m',states[dx]['times_s'],traces[dx],colors[dx]) for dx in [6.25,12.5,25.]]),
        dict(title='Final depth on the same common bed',x_label='distance (m)',y_label='depth (m)',xlim=(0,2200),series=[(f'{dx:g}m',states[dx]['cell_center_m'],states[dx]['depth_m'][-1],colors[dx]) for dx in [6.25,12.5,25.]]),
        dict(title='Volume position (95% stored volume)',x_label='relative time (s)',y_label='distance (m)',series=[(f'{dx:g}m',snap[snap.dx_m==dx].time_s,snap[snap.dx_m==dx]['mass_0.95_position_m'],colors[dx]) for dx in [6.25,12.5,25.]]),
        dict(title='Kinetic energy proxy (per density)',x_label='relative time (s)',y_label='m5/s2',series=[(f'{dx:g}m',snap[snap.dx_m==dx].time_s,snap[snap.dx_m==dx].kinetic_energy_per_density_m5_s2,colors[dx]) for dx in [6.25,12.5,25.]])],size=(1800,1200))
    v=pd.DataFrame(samples); aligned=pd.DataFrame(aligned_rows); pair='12.5_vs_25'; line=aligned[aligned.pair==pair]; vv=v[v.pair==pair]
    save_multi_panel(OUT/'velocity_and_peak_alignment.png',[
        dict(title='12.5 vs 25m: absolute speed error (wet union)',x_label='relative time (s)',y_label='MAE (m/s)',series=[('MAE',vv.time_s,vv.velocity_wet_union_MAE_m_s,'#2563eb')]),
        dict(title='12.5 vs 25m: velocity relative error',x_label='relative time (s)',y_label='relative L1',series=[('raw all',vv.time_s,vv.raw_unfiltered_velocity_relative,'#64748b'),('common wet',vv.time_s,vv.raw_commonwet_velocity_relative,'#dc2626'),('active >0.1m/s',vv.time_s,vv.active_velocity_relative,'#2563eb')]),
        dict(title='1000m: alignment is auxiliary, not validation',x_label='relative time (s)',y_label='Q (m3/s)',series=[('12.5m',line.time_s,line.fine_Q,'#2563eb'),('25m original',line.time_s,line.coarse_Q,'#64748b'),('25m peak aligned',line.time_s,line.peak_aligned_coarse_Q,'#dc2626')]),
        dict(title='Unit-width momentum difference, no speed mask',x_label='relative time (s)',y_label='space L1 (m3/s)',series=[('12.5 vs25',vv.time_s,vv.momentum_abs_L1_m3_s,'#2563eb')])],size=(1800,1200))
    meta=dict(started_utc=started,ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),solver_sha256=code_sha,common_bed_sha256=sha(profile_path),state_sources=sources,only_new_grid_m=6.25,python=sys.executable,parameters=parameters,all_states_finite=all(np.isfinite(r['depth_m']).all() and np.isfinite(r['velocity_m_s']).all() for r in states.values()))
    (OUT/'run_provenance.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(pd.DataFrame(grids).to_string(index=False)); print(pd.DataFrame(comparisons).to_string(index=False)); print(pd.DataFrame(hydrostats).to_string(index=False)); print(pd.DataFrame(stages).to_string(index=False))

if __name__=='__main__': main()
