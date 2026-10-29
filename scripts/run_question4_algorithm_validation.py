"""Versioned standard/real-bed runs; physical inputs inherited unchanged from v1."""
from pathlib import Path
import argparse, json, hashlib
import numpy as np
import pandas as pd
from q4_solver_registry import execute

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/question4/algorithm_validation'
SOLVERS={'baseline':'question4_dynamics_v1_reference.py','boundary':'question4_boundary_candidate.py','candidate':'question4_friction_candidate.py'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--solver',choices=SOLVERS,required=True)
    ap.add_argument('--terrain',nargs='+',default=['flat','slope','smooth'])
    ap.add_argument('--dx',type=float,nargs='+',default=[12.5,25,50,100,200])
    ap.add_argument('--horizon',type=float,default=1800); args=ap.parse_args()
    source=ROOT/'scripts'/SOLVERS[args.solver]
    code_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    cfg=json.loads((ROOT/'config/question4-simulation.json').read_text(encoding='utf-8'))
    ref=cfg['scenarios'][0]; p=cfg['physical_parameters']; num=cfg['numerics']
    event=json.loads((ROOT/cfg['model']['event_context_summary']).read_text(encoding='utf-8'))
    length=event['route_candidates'][0]['centerline_distance_km']*1000
    dest=OUT/args.solver/code_sha; dest.mkdir(parents=True,exist_ok=True)
    rows=[]; metrics=[]; hydro=[]; index=[]
    if 'real' in args.terrain:
        gate=json.loads((OUT/'standard_gate.json').read_text())
        candidate_sha=hashlib.sha256((ROOT/'scripts'/SOLVERS['candidate']).read_bytes()).hexdigest()
        if not gate.get('passed') or gate.get('solver_sha256')!=candidate_sha: raise RuntimeError('Current candidate has no passing standard gate; real DEM run forbidden')
    for terrain in args.terrain:
        for dx in args.dx:
            n=int(np.ceil(length/dx)); x=(np.arange(n)+.5)*length/n
            if terrain=='flat': z=x*0
            elif terrain=='slope': z=-.15*x
            elif terrain=='smooth': z=-.03*x+20*np.sin(2*np.pi*x/2000)
            elif terrain=='real':
                profile=pd.read_csv(ROOT/'output/question4/convergence_diagnostics/common_bed_profile.csv')
                z=np.interp(x,profile.distance_m,profile.corrected_z_m)
            else: raise ValueError(terrain)
            kw=dict(x_m=x,bed_m=z,width_m=ref['width_m'],volume_m3=ref['volume_m3'],pulse_duration_s=p['pulse_duration_s']['value'],inlet_depth_m=p['inlet_depth_m']['value'],mu=ref['mu'],xi_m_s2=ref['xi_m_s2'],end_time_s=args.horizon,cfl=num['cfl_number'],output_interval_s=num['output_interval_s'])
            tag=f'{terrain}_{dx:g}_{args.horizon:g}'
            try:
                r,cache=execute(source,kw,OUT/'cache',args.solver)
                index.append(dict(case=tag,terrain=terrain,dx_m=dx,path=cache.relative_to(ROOT).as_posix(),solver_sha256=code_sha))
                rows.append(dict(case=tag,terrain=terrain,dx_m=dx,actual_dx_m=float(r['cell_width_m']),solver=args.solver,solver_sha256=code_sha,status='completed',front_m=float(r['max_front_position_m']),peak_speed_m_s=float(np.max(abs(r['velocity_m_s']))),mass_error=float(r['relative_mass_error']),storage_m3=float(r['final_mass_m3']),input_m3=float(r['injected_volume_m3']),outflow_m3=float(r['outlet_volume_m3']),min_h_m=float(r['depth_m'].min()),max_cfl=float(r['max_cfl_number'])))
                for i,t in enumerate(r['times_s']):
                    h=r['depth_m'][i]; mass=np.cumsum(h); total=mass[-1]
                    row=dict(case=tag,time_s=t,mass_centroid_m=float(np.dot(x,h)/total) if total>0 else np.nan)
                    for f in [.5,.95,.99]:
                        # Piecewise uniform mass within cells, interpolating between cell edges.
                        row[f'mass_position_{f:g}_m']=float(np.interp(f*total,np.r_[0,mass],np.r_[0,x+length/n/2])) if total>0 else np.nan
                    for th in [.001,.01,.05]:
                        wet=np.flatnonzero(h>th); row[f'front_h{th:g}_m']=float(x[wet[-1]]) if wet.size else 0.
                    metrics.append(row)
                    for sec in [500,1000,2000]: hydro.append(dict(case=tag,time_s=t,section_m=sec,h_m=np.interp(sec,x,h),u_m_s=np.interp(sec,x,r['velocity_m_s'][i]),physical_Q_m3_s=np.interp(sec,x,r['discharge_m3_s'][i])))
                print(args.solver,tag,rows[-1]['front_m'],flush=True)
            except Exception as exc:
                rows.append(dict(case=tag,terrain=terrain,dx_m=dx,solver_sha256=code_sha,status=repr(exc))); print(tag,repr(exc),flush=True)
    suffix='_'.join(args.terrain)+f'_{args.horizon:g}'
    for name,data in [('experiments',rows),('front_mass_metrics',metrics),('hydrographs',hydro),('run_index',index)]:
        pd.DataFrame(data).to_csv(dest/f'{name}_{suffix}.csv',index=False,encoding='utf-8-sig')
    (dest/'run_arguments.json').write_text(json.dumps(vars(args),indent=2))

if __name__=='__main__': main()
