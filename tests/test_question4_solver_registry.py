import tempfile
import unittest
from pathlib import Path
import numpy as np
from scripts.q4_solver_registry import execute, fingerprint

class RegistryTests(unittest.TestCase):
    def test_code_identity_and_input_identity_isolate_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); a=root/'a.py'; b=root/'b.py'
            a.write_text('def run_simulation(**kw): return {"answer": 1}\n')
            b.write_text('def run_simulation(**kw): return {"answer": 2}\n')
            kw={'x_m':np.arange(3.),'bed_m':np.zeros(3)}
            ra,pa=execute(a,kw,root/'cache','baseline')
            rb,pb=execute(b,kw,root/'cache','candidate')
            self.assertNotEqual(pa,pb); self.assertEqual(ra['answer'],1); self.assertEqual(rb['answer'],2)
            a.write_text('def run_simulation(**kw): return {"answer": 3}\n')
            rc,pc=execute(a,kw,root/'cache','baseline')
            self.assertNotEqual(pa,pc); self.assertEqual(rc['answer'],3)
            self.assertNotEqual(fingerprint(a,kw),fingerprint(a,{**kw,'bed_m':np.ones(3)}))

    def test_cache_has_no_pickle_and_code_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); a=root/'a.py'; a.write_text('def run_simulation(**kw): return {"depth_m": [1.,2.]}\n')
            _,p=execute(a,{},root/'cache','candidate')
            self.assertTrue((p/'manifest.json').exists())
            with np.load(p/'state.npz',allow_pickle=False) as data: self.assertEqual(data['depth_m'].size,2)
