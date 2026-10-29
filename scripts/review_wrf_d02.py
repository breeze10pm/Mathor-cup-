"""Read-only WRF nest review. Pass the downloaded file with --d02."""
from pathlib import Path
import argparse,json,hashlib
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from netCDF4 import Dataset,chartostring
from pyproj import Geod
from question4_visuals import save_multi_panel

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/wrf_d02_review'
SITES={'source_A':(28.285317,85.525155),'source_B':(28.288708,85.528159),'port':(28.2785,85.3766)}
GEOD=Geod(ellps='WGS84')
def arr(v): return np.asarray(np.ma.filled(v,np.nan),dtype=float)
def save(rows,name): pd.DataFrame(rows).to_csv(OUT/name,index=False,encoding='utf-8-sig')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--d02',required=True,type=Path); args=ap.parse_args(); OUT.mkdir(parents=True,exist_ok=True)
    variables=[]; points=[]; series=[]; summaries=[]; neighborhoods=[]; profiles=[]; metadata={}
    fields=['RAINC','RAINNC','RAINSH','T2','TSK','PSFC','Q2','U10','V10','PBLH','HGT','SNOW','SNOWH','ACSNOM','SFROFF','UDROFF','RUNSF','RUNSB','SWDOWN','GLW','HFX','LH','GRDFLX','FSA','FIRA','LU_INDEX','ISLTYP']
    for domain,path in [('d01',ROOT/'data/wrfout_d01_2026-08-25_00_00_00'),('d02',args.d02.resolve())]:
        with Dataset(path) as ds:
            times=[datetime.strptime(s,'%Y-%m-%d_%H:%M:%S').replace(tzinfo=timezone.utc) for s in chartostring(ds['Times'][:])]
            local=pd.DatetimeIndex(times).tz_convert('Asia/Shanghai')
            lat=arr(ds['XLAT'][0]); lon=arr(ds['XLONG'][0]); end_lat=arr(ds['XLAT'][-1]); end_lon=arr(ds['XLONG'][-1])
            attrs={k:ds.getncattr(k).item() if isinstance(ds.getncattr(k),np.generic) else ds.getncattr(k) for k in ds.ncattrs()}
            tail_errors=[]
            for name,var in ds.variables.items():
                variables.append(dict(domain=domain,name=name,dimensions=' '.join(var.dimensions),unit=str(getattr(var,'units','')),description=str(getattr(var,'description','')),shape=str(var.shape)))
                try: var[tuple(-1 for _ in var.shape)] if var.shape else var[...]
                except Exception as exc: tail_errors.append([name,str(exc)])
            surface={k:arr(ds[k][:]) for k in fields if k in ds.variables}
            rain=surface['RAINC']+surface['RAINNC']; increments=np.diff(rain,axis=0)
            ew=GEOD.inv(lon[:,:-1],lat[:,:-1],lon[:,1:],lat[:,1:])[2]; ns=GEOD.inv(lon[:-1],lat[:-1],lon[1:],lat[1:])[2]
            metadata[domain]=dict(filename=path.name,size_bytes=path.stat().st_size,sha256=sha(path),attributes=attrs,dimensions={k:len(v) for k,v in ds.dimensions.items()},first_utc=times[0].isoformat(),last_utc=times[-1].isoformat(),time_steps_seconds=sorted(set(np.diff([t.timestamp() for t in times]).tolist())),grid_moves=bool(np.max(abs(lat-end_lat))>1e-6 or np.max(abs(lon-end_lon))>1e-6),lat_range=[float(lat.min()),float(lat.max())],lon_range=[float(lon.min()),float(lon.max())],median_geodesic_ew_m=float(np.median(ew)),median_geodesic_ns_m=float(np.median(ns)),variable_tail_read_errors=tail_errors,negative_rain_increment_count=int((increments < -1e-5).sum()),surface_nonfinite_counts={k:int((~np.isfinite(v)).sum()) for k,v in surface.items()},generation_publication_time='not identified in global attributes; local mtime not evidence')
            for name,(plat,plon) in SITES.items():
                distance=GEOD.inv(np.full(lon.shape,plon),np.full(lat.shape,plat),lon,lat)[2]; row,col=np.unravel_index(distance.argmin(),distance.shape)
                d=dict(domain=domain,site=name,row=int(row),col=int(col),site_lat=plat,site_lon=plon,grid_lat=lat[row,col],grid_lon=lon[row,col],distance_m=distance[row,col],HGT_m=surface['HGT'][0,row,col],landuse=surface.get('LU_INDEX',np.full_like(rain,np.nan))[0,row,col],soil_type=surface.get('ISLTYP',np.full_like(rain,np.nan))[0,row,col]); points.append(d)
                total=rain[:,row,col]; inc=np.r_[np.nan,np.diff(total)]
                for i,t in enumerate(times):
                    record=dict(domain=domain,site=name,time_utc=t.isoformat(),time_beijing=local[i].isoformat(),rain_accum_mm=total[i],rain_increment_mm=inc[i],T2_C=surface['T2'][i,row,col]-273.15,wind10_speed_m_s=np.hypot(surface['U10'][i,row,col],surface['V10'][i,row,col]))
                    record.update({k:float(v[i,row,col]) for k,v in surface.items()}); series.append(record)
                for hour in [10,11]:
                    it=int(np.flatnonzero(local==pd.Timestamp(f'2026-08-26 {hour:02d}:00:00',tz='Asia/Shanghai'))[0])
                    window=distance<=5000
                    area_inc=increments[it-1][window]
                    neighborhoods.append(dict(domain=domain,site=name,end_hour_beijing=hour,radius_m=5000,grid_centers=int(window.sum()),rain_increment_min_mm=float(np.min(area_inc)) if area_inc.size else np.nan,rain_increment_max_mm=float(np.max(area_inc)) if area_inc.size else np.nan,rain_increment_mean_mm=float(np.mean(area_inc)) if area_inc.size else np.nan))
                    summaries.append({**d,'end_hour_beijing':hour,'rain_previous_hour_mm':inc[it],'rain_previous_6h_mm':total[it]-total[it-6],'rain_previous_24h_mm':total[it]-total[it-24],'T2_C':surface['T2'][it,row,col]-273.15,'SNOW_kg_m2':surface['SNOW'][it,row,col],'SNOWH_m':surface['SNOWH'][it,row,col],'ACSNOM_previous_24h_kg_m2':surface['ACSNOM'][it,row,col]-surface['ACSNOM'][it-24,row,col],'surface_runoff_previous_24h_mm':surface['SFROFF'][it,row,col]-surface['SFROFF'][it-24,row,col],'subsurface_runoff_previous_24h_mm':surface['UDROFF'][it,row,col]-surface['UDROFF'][it-24,row,col],'soil_moisture_top_m3_m3':float(ds['SMOIS'][it,0,row,col]),'soil_temp_top_K':float(ds['TSLB'][it,0,row,col])})
                    # At two bracketing times, inspect actual vertical thermal structure.
                    pressure=arr(ds['P'][it,:,row,col])+arr(ds['PB'][it,:,row,col]); theta=arr(ds['T'][it,:,row,col])+300
                    temp=theta*(pressure/100000)**(287/1004)-273.15
                    zs=(arr(ds['PH'][it,:,row,col])+arr(ds['PHB'][it,:,row,col]))/9.81; zm=.5*(zs[1:]+zs[:-1])
                    for k in range(len(temp)): profiles.append(dict(domain=domain,site=name,end_hour_beijing=hour,level=k,height_geopotential_m=zm[k],pressure_Pa=pressure[k],temperature_C=temp[k],qvapor_kg_kg=float(ds['QVAPOR'][it,k,row,col])))
    save(variables,'variable_inventory.csv');save(points,'site_grid_comparison.csv');save(series,'site_timeseries.csv');save(summaries,'event_comparison.csv');save(neighborhoods,'rain_5km_neighborhood.csv');save(profiles,'event_vertical_profiles.csv')
    (OUT/'metadata.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf-8')
    table=pd.DataFrame(series); panels=[]
    for site in SITES:
        for field,title,unit in [('rain_increment_mm','Previous-hour model precipitation','mm'),('T2_C','Model 2 m temperature','deg C')]:
            plots=[]
            for domain,color in [('d01','#64748b'),('d02','#2563eb')]:
                t=table[(table.site==site)&(table.domain==domain)]; hours=(pd.to_datetime(t.time_beijing)-pd.Timestamp('2026-08-26 10:00:00+08:00')).dt.total_seconds()/3600
                plots.append((domain,hours,t[field],color))
            panels.append(dict(title=site+': '+title,x_label='hours from Aug26 10:00 BJT',y_label=unit,xlim=(-24,6),series=plots))
    save_multi_panel(OUT/'d01_d02_event_comparison.png',panels,size=(1800,1600))
    print(pd.DataFrame(summaries).to_string(index=False));print(pd.DataFrame(neighborhoods).to_string(index=False))

if __name__=='__main__': main()
