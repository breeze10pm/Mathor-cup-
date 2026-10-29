import unittest
import numpy as np
from scripts import question4_friction_candidate as s

class FrictionTests(unittest.TestCase):
    def run_model(self,x,h,mu=.1,end=60,z=None,velocity=None):
        kw=dict(x_m=x,bed_m=np.zeros_like(x) if z is None else z,width_m=20.,volume_m3=0.,pulse_duration_s=10.,inlet_depth_m=2.,initial_depth_profile_m=h,mu=mu,xi_m_s2=1e30,end_time_s=end,cfl=.35,output_interval_s=min(5,end))
        if velocity is not None: kw['initial_velocity_profile_m_s']=velocity
        return s.run_simulation(**kw)
    def test_static_triangular_pile_and_dry_margin(self):
        x=np.arange(.5,600,1.); h=np.maximum(0,3-.05*abs(x-300))
        r=self.run_model(x,h)
        self.assertLess(np.max(abs(r['depth_m'][-1]-h)),1e-9)
        self.assertLess(np.max(abs(r['velocity_m_s'])),1e-9)
        self.assertLess(r['relative_mass_error'],1e-10)
    def test_above_repose_pile_starts(self):
        x=np.arange(.5,600,1.); h=np.maximum(0,3-.2*abs(x-300))
        r=self.run_model(x,h,end=5)
        self.assertGreater(np.max(abs(r['depth_m'][-1]-h)),.01)
    def test_static_nonflat_bed(self):
        x=np.arange(.5,600,1.); z=.015*np.sin(x/20); h=np.maximum(0,3-.04*abs(x-300))
        r=self.run_model(x,h,z=z)
        self.assertLess(np.max(abs(r['depth_m'][-1]-h)),1e-9)
    def test_uniform_flow_stops_without_reversing(self):
        x=np.arange(.5,600,1.); h=np.ones_like(x)*2
        r=self.run_model(x,h,end=3,velocity=np.ones_like(x))
        self.assertLess(np.max(abs(r['velocity_m_s'][-1,200:400])),1e-8)
        self.assertGreaterEqual(np.min(r['velocity_m_s'][:,200:400]),-1e-8)
    def test_frictionless_dry_dam_break_against_ritter(self):
        errors=[]
        for dx in [2.,1.]:
            x=np.arange(dx/2,600,dx); h=np.where(x<300,3.,0.); t=5.
            r=self.run_model(x,h,mu=0,end=t)
            c=np.sqrt(s.GRAVITY_M_S2*3); v=(x-300)/t
            exact=np.where(v<-c,3,np.where(v>2*c,0,(2*c-v)**2/(9*s.GRAVITY_M_S2)))
            errors.append(np.sum(abs(r['depth_m'][-1]-exact))*dx)
            self.assertGreaterEqual(r['depth_m'].min(),0)
            self.assertTrue(np.isfinite(r['velocity_m_s']).all())
            self.assertLess(r['relative_mass_error'],1e-10)
        self.assertLess(errors[1],errors[0]); self.assertLess(errors[1]/900,.02)
    def test_zero_inflow_dry_domain(self):
        x=np.arange(.5,100,1.); r=self.run_model(x,x*0,end=10)
        self.assertEqual(r['final_mass_m3'],0.)
    def test_stationary_pile_has_no_numerical_mass_creep(self):
        x=np.arange(.5,600,1.); h=np.maximum(0,3-.05*abs(x-300))
        flux=s._interface_fluxes(h,h*0,h*0,2.,0.,dt=.01,dx=1.,mu=.1)[0]
        self.assertLess(np.max(abs(flux)),1e-12)
    def test_rectangular_inlet_mass_and_cfl(self):
        x=np.arange(2.5,2000,5.)
        r=s.run_simulation(x_m=x,bed_m=x*0,width_m=20.,volume_m3=2000.,pulse_duration_s=10.,inlet_depth_m=2.,mu=.1,xi_m_s2=300.,end_time_s=30.,cfl=.35,output_interval_s=1.)
        self.assertAlmostEqual(r['injected_volume_m3'],2000.,places=7)
        self.assertLess(r['relative_mass_error'],1e-10)
        self.assertLessEqual(r['max_cfl_number'],.35000001)
        self.assertGreaterEqual(r['depth_m'].min(),0.)
