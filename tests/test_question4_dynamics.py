"""Numerical checks for the isolated one-dimensional Q4 solver."""

import unittest

import numpy as np

from rasterio.transform import from_origin

from scripts.question4_dynamics import prepare_uniform_profile, run_simulation, sample_raster_nearest


class TestQuestion4Dynamics(unittest.TestCase):
    def setUp(self):
        self.x = np.arange(0.0, 2000.0 + 10.0, 10.0)
        self.bed = -0.03 * self.x

    def run_case(self, *, mu=0.05, xi=200.0, dx=None, volume=2000.0, width=20.0, cfl=0.4):
        x = self.x if dx is None else np.arange(0.0, 2000.0 + dx, dx)
        bed = -0.03 * x
        return run_simulation(
            x_m=x,
            bed_m=bed,
            width_m=width,
            volume_m3=volume,
            pulse_duration_s=10.0,
            inlet_depth_m=2.0,
            mu=mu,
            xi_m_s2=xi,
            end_time_s=30.0,
            cfl=cfl,
            output_interval_s=1.0,
        )

    def test_zero_inflow_dry_domain_stays_dry(self):
        result = run_simulation(
            x_m=self.x,
            bed_m=self.bed,
            width_m=20.0,
            volume_m3=0.0,
            pulse_duration_s=10.0,
            inlet_depth_m=2.0,
            mu=0.1,
            xi_m_s2=200.0,
            end_time_s=5.0,
            cfl=0.4,
            output_interval_s=1.0,
        )
        self.assertAlmostEqual(result["final_mass_m3"], 0.0, places=12)
        self.assertLess(float(np.max(result["depth_m"])), 1e-12)

    def test_lake_at_rest_is_well_balanced_over_sloping_bed(self):
        bed = -0.01 * self.x
        initial_depth = 20.0 - bed
        result = run_simulation(
            x_m=self.x,
            bed_m=bed,
            width_m=20.0,
            volume_m3=0.0,
            pulse_duration_s=10.0,
            inlet_depth_m=2.0,
            initial_depth_profile_m=initial_depth,
            mu=0.0,
            xi_m_s2=1e6,
            end_time_s=5.0,
            cfl=0.4,
            output_interval_s=1.0,
        )
        self.assertLess(float(np.max(np.abs(result["velocity_m_s"]))), 1e-8)
        self.assertLess(float(np.max(np.abs(result["depth_m"][-1] - initial_depth))), 1e-8)


    def test_rectangular_inlet_pulse_closes_mass_balance(self):
        result = run_simulation(
            x_m=self.x,
            bed_m=np.zeros_like(self.x),
            width_m=20.0,
            volume_m3=2000.0,
            pulse_duration_s=10.0,
            inlet_depth_m=2.0,
            mu=0.0,
            xi_m_s2=1e6,
            end_time_s=5.0,
            cfl=0.4,
            output_interval_s=1.0,
        )
        self.assertAlmostEqual(result["injected_volume_m3"], 1000.0, delta=1e-8)
        self.assertLess(result["relative_mass_error"], 1e-8)
        self.assertAlmostEqual(result["final_mass_m3"], 1000.0, delta=1e-6)

    def test_depth_velocity_and_discharge_are_finite_and_depth_nonnegative(self):
        result = self.run_case()
        for name in ("depth_m", "velocity_m_s", "discharge_m3_s"):
            self.assertTrue(np.isfinite(result[name]).all(), name)
        self.assertGreaterEqual(float(result["depth_m"].min()), 0.0)
        self.assertTrue(np.isfinite(result["mass_balance"]).all())

    def test_profile_resampling_preserves_downhill_orientation_and_rejects_nodata(self):
        source = {
            "chainage_m": np.array([100.0, 250.0, 400.0]),
            "elev_m": np.array([1200.0, 1100.0, 900.0]),
        }
        x, z = prepare_uniform_profile(source, 100.0, 400.0, 50.0)
        self.assertTrue(np.all(np.diff(x) > 0))
        self.assertTrue(np.all(np.diff(z) < 0))
        broken = {"chainage_m": source["chainage_m"], "elev_m": np.array([1200.0, np.nan, 900.0])}
        with self.assertRaises(ValueError):
            prepare_uniform_profile(broken, 100.0, 400.0, 50.0)

    def test_dem_sampler_rejects_zero_nodata_and_outside_cells(self):
        raster = np.array([[10.0, 11.0], [12.0, 0.0]])
        transform = from_origin(0.0, 2.0, 1.0, 1.0)
        values, diagnostics = sample_raster_nearest(
            raster, transform, [0.5], [1.5], "EPSG:32645", "EPSG:32645", nodata_value=-9999.0
        )
        self.assertEqual(values.tolist(), [10.0])
        self.assertEqual(diagnostics["valid_count"], 1)
        with self.assertRaises(ValueError):
            sample_raster_nearest(raster, transform, [1.5], [0.5], "EPSG:32645", "EPSG:32645", nodata_value=-9999.0)
        with self.assertRaises(ValueError):
            sample_raster_nearest(raster, transform, [9.5], [9.5], "EPSG:32645", "EPSG:32645", nodata_value=-9999.0)

    def test_higher_resistance_does_not_increase_runout_in_controlled_case(self):
        low = self.run_case(mu=0.01, xi=1000.0)
        high = self.run_case(mu=0.20, xi=50.0)
        self.assertLessEqual(high["max_front_position_m"], low["max_front_position_m"] + 1e-6)

    def test_grid_refinement_is_stable_for_front_position(self):
        coarse = self.run_case(dx=10.0)
        fine = self.run_case(dx=5.0)
        scale = max(fine["max_front_position_m"], 1.0)
        self.assertLess(abs(coarse["max_front_position_m"] - fine["max_front_position_m"]) / scale, 0.1)
        self.assertLess(coarse["relative_mass_error"], 1e-8)
        self.assertLess(fine["relative_mass_error"], 1e-8)

    def test_cfl_step_change_preserves_front_and_mass(self):
        low_cfl = self.run_case(cfl=0.2)
        high_cfl = self.run_case(cfl=0.4)
        scale = max(low_cfl["max_front_position_m"], 1.0)
        self.assertLess(abs(low_cfl["max_front_position_m"] - high_cfl["max_front_position_m"]) / scale, 0.05)
        self.assertLess(low_cfl["relative_mass_error"], 1e-8)
        self.assertLess(high_cfl["relative_mass_error"], 1e-8)


if __name__ == "__main__":
    unittest.main()
