"""Explicit solver and input addressed experiment cache. No old NPZ discovery."""
import hashlib
import json
import types
from pathlib import Path
import numpy as np

def manifest(source, kwargs):
    inputs={}
    for k,v in sorted(kwargs.items()):
        if isinstance(v,np.ndarray):
            a=np.ascontiguousarray(v)
            inputs[k]={'shape':list(a.shape),'dtype':str(a.dtype),'sha256':hashlib.sha256(a.tobytes()).hexdigest()}
        else: inputs[k]=v
    return {'schema':1,'solver_file':source.name,'solver_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'registry_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'inputs':inputs}

def fingerprint(source,kwargs):
    return hashlib.sha256(json.dumps(manifest(source,kwargs),sort_keys=True).encode()).hexdigest()

def execute(source,kwargs,cache_root,label):
    source=Path(source); meta=manifest(source,kwargs)
    dest=Path(cache_root)/label/fingerprint(source,kwargs)
    dest.mkdir(parents=True,exist_ok=True)
    m=dest/'manifest.json'; state=dest/'state.npz'
    if state.exists():
        if json.loads(m.read_text())!=meta: raise RuntimeError('Cache manifest mismatch')
        with np.load(state,allow_pickle=False) as data: return {k:data[k] for k in data.files},dest
    module=types.ModuleType('isolated_q4_solver')
    # Compile source directly: avoid timestamp/size based .pyc cache ambiguity.
    exec(compile(source.read_bytes(),str(source),'exec'),module.__dict__)
    result=module.run_simulation(**kwargs)
    (dest/source.name).write_bytes(source.read_bytes())
    m.write_text(json.dumps(meta,indent=2),encoding='utf-8')
    np.savez_compressed(state,**{k:v for k,v in result.items() if k!='mass_balance_columns'})
    return result,dest
