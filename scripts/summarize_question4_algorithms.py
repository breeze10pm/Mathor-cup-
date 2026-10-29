"""Cross-code and multi-metric comparison of explicitly versioned runs."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from question4_visuals import save_multi_panel
from run_question4_algorithm_validation import ROOT,OUT,SOLVERS

def save(rows,name): pd.DataFrame(rows).to_csv(OUT/name,index=False,encoding='utf-8-sig')
def main():
    all_e=[]; all_m=[]; all_h=[]; entries=[]; versions={}
    for solver,file in SOLVERS.items():
        sha=hashlib.sha256((ROOT/'scripts'/file).read_bytes()).hexdigest(); versions[solver]=sha; d=OUT/solver/sha
        for prefix,target in [('experiments',all_e),('front_mass_metrics',all_m),('hydrographs',all_h),('run_index',entries)]:
            for p in d.glob(prefix+'_*_1800.csv'):
                df=pd.read_csv(p); df['solver']=solver; target.append(df)
    e=pd.concat(all_e,ignore_index=True).drop_duplicates(['solver','case']); m=pd.concat(all_m,ignore_index=True).drop_duplicates(['solver','case','time_s']); hyd=pd.concat(all_h,ignore_index=True).drop_duplicates(['solver','case','time_s','section_m']); ind=pd.concat(entries,ignore_index=True).drop_duplicates(['solver','case'])
    save(e,'stage_comparison.csv'); save(m,'mass_position_comparison.csv'); save(hyd,'section_hydrographs.csv'); save(ind,'run_index.csv')
    rows=[]
    def err(a,b):
        den=np.sum(abs(a)); return float(np.sum(abs(a-b))/den) if den>1e-8 else np.nan
    for solver in SOLVERS:
        for terrain in ['flat','slope','smooth','real']:
            for fine,coarse in [(12.5,25),(25,50),(50,100),(100,200)]:
                tags=[f'{terrain}_{dx:g}_1800' for dx in [fine,coarse]]
                paths=[ROOT/ind[(ind.solver==solver)&(ind.case==tag)].iloc[0].path/'state.npz' for tag in tags]
                with np.load(paths[0]) as a,np.load(paths[1]) as b:
                    x=a['cell_center_m']; xb=b['cell_center_m']
                    common=dict(solver=solver,terrain=terrain,fine_dx_m=fine,coarse_dx_m=coarse)
                    for tt in [300,600,1200,1800]:
                        i=np.argmin(abs(a['times_s']-tt)); j=np.argmin(abs(b['times_s']-tt))
                        for key in ['depth_m','velocity_m_s']:
                            av=a[key][i]; bv=np.interp(x,xb,b[key][j]); mask=(a['depth_m'][i]>.05)&(np.interp(x,xb,b['depth_m'][j])>.05) if key=='velocity_m_s' else np.ones(len(x),bool)
                            rows.append({**common,'metric':key,'time_s':tt,'relative_difference':err(av[mask],bv[mask])})
                    for key in ['max_front_position_m']:
                        rows.append({**common,'metric':'max_front_m','time_s':1800,'relative_difference':abs(float(a[key]-b[key]))/max(abs(float(a[key])),1e-8)})
                    rows.append({**common,'metric':'peak_speed_m_s','time_s':1800,'relative_difference':abs(abs(a['velocity_m_s']).max()-abs(b['velocity_m_s']).max())/max(abs(a['velocity_m_s']).max(),1e-8)})
                for sec in [500,1000,2000]:
                    values=[hyd[(hyd.solver==solver)&(hyd.case==tag)&(hyd.section_m==sec)].sort_values('time_s').physical_Q_m3_s.values for tag in tags]
                    rows.append({**common,'metric':f'Q_{sec}_L1','time_s':1800,'relative_difference':err(*values)})
                for key in ['mass_centroid_m','mass_position_0.5_m','mass_position_0.95_m','mass_position_0.99_m']:
                    values=[float(m[(m.solver==solver)&(m.case==tag)&(m.time_s==1800)].iloc[0][key]) for tag in tags]
                    rows.append({**common,'metric':key,'time_s':1800,'relative_difference':abs(values[0]-values[1])/max(abs(values[0]),1e-8)})
    conv=pd.DataFrame(rows); conv['within_5pct_screen']=conv.relative_difference.map(lambda v: bool(v<.05) if pd.notna(v) else None); save(conv,'grid_convergence_metrics.csv')
    panels=[]
    for terrain in ['flat','slope','smooth','real']:
        series=[]
        for solver,col in zip(SOLVERS,['#64748b','#2563eb','#dc2626']):
            df=e[(e.solver==solver)&(e.terrain==terrain)].sort_values('dx_m'); series.append((solver,df.dx_m,df.front_m/1000,col))
        panels.append(dict(title=terrain+' same physical inputs',x_label='requested grid dx (m)',y_label='max front (km)',series=series))
    save_multi_panel(OUT/'algorithm_grid_comparison.png',panels,size=(1800,1200))
    last=m[m.time_s==1800].copy(); last['dx_m']=last.case.str.split('_').str[1].astype(float); last['terrain']=last.case.str.split('_').str[0]
    series=[]
    for solver,col in zip(SOLVERS,['#64748b','#2563eb','#dc2626']):
        df=last[(last.solver==solver)&(last.terrain=='real')].sort_values('dx_m'); series.append((solver,df.dx_m,df['mass_position_0.95_m'],col))
    save_multi_panel(OUT/'real_mass_position.png',[dict(title='Real bed: 95% stored-volume position at 1800s',x_label='requested grid dx (m)',y_label='distance (m)',series=series)],size=(1200,650))
    (OUT/'versions.json').write_text(json.dumps(versions,indent=2))
    print(e[['solver','terrain','dx_m','front_m']].to_string(index=False))
    print('CANDIDATE REAL FINEST PAIR'); print(conv[(conv.solver=='candidate')&(conv.terrain=='real')&(conv.fine_dx_m==12.5)].to_string(index=False))

if __name__=='__main__': main()
