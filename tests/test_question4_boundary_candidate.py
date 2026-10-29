import unittest
import numpy as np
from scripts import question4_boundary_candidate as s

class BoundaryTests(unittest.TestCase):
    def test_supercritical_pair_consistent_despite_interior_depth(self):
        for h0 in [0.,3.,6.,12.]:
            fh,fl,fr,*_=s._interface_fluxes(np.array([h0,0.,0.]),np.zeros(3),np.zeros(3),3.,50.)
            self.assertAlmostEqual(fh[0],50.)
            self.assertAlmostEqual(fr[0],50**2/3+.5*s.GRAVITY_M_S2*9)
    def test_after_pulse_wall_has_zero_mass_flux(self):
        h=np.ones(3)*3; q=np.ones(3)*2
        fh,fl,fr,*_=s._interface_fluxes(h,q,np.zeros(3),3.,0.)
        expected=s._hll_flux(np.array([3.]),np.array([-2.]),np.array([3.]),np.array([2.]))[1][0]
        self.assertEqual(fh[0],0.); self.assertAlmostEqual(fr[0],expected)
    def test_subcritical_characteristic(self):
        h,q,reg=s.inlet_state(1.,3.,4.,2.)
        self.assertEqual(reg,'subcritical')
        self.assertAlmostEqual(q/h-2*np.sqrt(s.GRAVITY_M_S2*h),.5-2*np.sqrt(s.GRAVITY_M_S2*4),places=10)
        self.assertEqual(q,1.)
    def test_subcritical_dry_interior_rejected(self):
        with self.assertRaises(ValueError): s.inlet_state(1.,3.,0.,0.)
