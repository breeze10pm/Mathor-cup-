"""Independent simple signals check supplementary time-axis calculations."""
from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from supplement_question4_acceptance import hydro_compare,ratio

class AcceptanceMetrics(unittest.TestCase):
    def test_identical_hydrographs_have_zero_errors(self):
        t=np.arange(101.); q=np.maximum(0,1-abs(t-50)/10)
        d,_,_=hydro_compare(t,q,q)
        self.assertEqual(d['raw_L1_relative'],0.)
        self.assertAlmostEqual(d['fine_net_volume_m3'],10.)
    def test_known_pure_delay_is_removed_only_in_auxiliary_alignment(self):
        t=np.arange(101.); a=np.maximum(0,1-abs(t-40)/10); b=np.maximum(0,1-abs(t-45)/10)
        d,_,_=hydro_compare(t,a,b)
        self.assertEqual(d['coarse_peak_delay_s'],5.)
        self.assertGreater(d['raw_L1_relative'],0.)
        self.assertEqual(d['peak_aligned_L1_relative'],0.)
        self.assertAlmostEqual(d['fine_net_volume_m3'],d['coarse_net_volume_m3'])
    def test_zero_denominator_remains_missing(self):
        self.assertTrue(np.isnan(ratio(0,0)))
