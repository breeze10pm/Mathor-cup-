"""Record an explicit BASIC standard-test gate, distinct from grid convergence."""
from pathlib import Path
import hashlib,json,sys,unittest,datetime
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
OUT=ROOT/'output/question4/algorithm_validation'
source=ROOT/'scripts/question4_friction_candidate.py'; sha=hashlib.sha256(source.read_bytes()).hexdigest()
suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_question4_solver_registry','tests.test_question4_boundary_candidate','tests.test_question4_friction_candidate'])
start=datetime.datetime.now(datetime.timezone.utc).isoformat()
with (OUT/'standard_tests_final.log').open('w',encoding='utf-8') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
df=pd.read_csv(OUT/'candidate'/sha/'experiments_flat_slope_smooth_1800.csv')
stable=bool(len(df)==15 and df.status.eq('completed').all() and (df.min_h_m>=0).all() and (df.mass_error<1e-8).all() and (df.max_cfl<.350001).all())
gate=dict(passed=result.wasSuccessful() and stable,scope='basic analytic/equilibrium/stability tests only; NOT a grid-convergence gate',solver_sha256=sha,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),long_standard_runs=len(df),long_standard_stability_passed=stable,started_utc=start,ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),python=sys.executable,command='python scripts/gate_question4_candidate.py',grid_convergence_passed=False)
(OUT/'standard_gate.json').write_text(json.dumps(gate,indent=2),encoding='utf-8'); print(json.dumps(gate,indent=2))
if not gate['passed']: raise SystemExit(1)
