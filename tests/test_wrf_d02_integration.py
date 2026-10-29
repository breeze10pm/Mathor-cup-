"""Small, independent checks of window semantics and missing-data handling."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from integrate_wrf_d02 import window_values, aware_time, context_kind


class WindowChecks(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            'time_beijing': pd.date_range('2026-08-26 08:00', periods=4, freq='h', tz='Asia/Shanghai'),
            'rain_accum_mm': [0., 1., 3., 13.],
            'rain_increment_mm': [np.nan, 1., 2., 10.],
            'T2_C': [2., 4., 6., 8.],
        })

    def test_windows_exclude_cross_event_hour(self):
        r = window_values(self.frame, '2026-08-26T10:00:00+08:00', 2)
        self.assertEqual(r['rain_mm'], 3.)
        self.assertEqual(r['T2_sample_mean_C'], 5.)
        self.assertEqual(r['sample_count'], 2)
        self.assertEqual(context_kind('2026-08-26T11:00:00+08:00'), 'cross_event')

    def test_timezone_conversion(self):
        self.assertEqual(aware_time('2026-08-26T10:00:00+08:00').tz_convert('UTC').hour, 2)
        with self.assertRaises(ValueError):
            aware_time('2026-08-26 10:00')

    def test_missing_hour_not_filled(self):
        with self.assertRaises(ValueError):
            window_values(self.frame.drop(index=1), '2026-08-26T10:00:00+08:00', 2)

    def test_duplicate_hour_rejected(self):
        with self.assertRaises(ValueError):
            window_values(pd.concat([self.frame, self.frame.iloc[[1]]]), '2026-08-26T10:00:00+08:00', 2)

    def test_reset_rejected(self):
        f = self.frame.copy()
        f.loc[2, 'rain_accum_mm'] = 0.
        with self.assertRaises(ValueError):
            window_values(f, '2026-08-26T10:00:00+08:00', 2)

    def test_unknown_temperature_preserved(self):
        f = self.frame.copy()
        f.loc[1, 'T2_C'] = np.nan
        r = window_values(f, '2026-08-26T10:00:00+08:00', 2)
        self.assertTrue(np.isnan(r['T2_sample_mean_C']))

    def test_unknown_rain_is_error_not_zero(self):
        f = self.frame.copy()
        f.loc[1, 'rain_accum_mm'] = np.nan
        with self.assertRaises(ValueError):
            window_values(f, '2026-08-26T10:00:00+08:00', 2)

    def test_window_can_be_requested_in_utc(self):
        r = window_values(self.frame, '2026-08-26T02:00:00+00:00', 2)
        self.assertEqual(r['rain_mm'], 3.)


if __name__ == '__main__':
    unittest.main()
