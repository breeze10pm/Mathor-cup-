"""Regression evidence for pixel-center indexing, independent of real DEM."""
import unittest
import numpy as np
from rasterio.transform import from_origin
from scripts.question4_dynamics import sample_raster_nearest

class TestPixelIndex(unittest.TestCase):
    def test_noncenter_coordinate_uses_containing_nearest_center(self):
        raster=np.array([[10.,20.],[30.,40.]])
        z,_=sample_raster_nearest(raster,from_origin(0,2,1,1),np.array([.9,1.1]),np.array([1.1,1.9]),'EPSG:32645','EPSG:32645',-9999.)
        np.testing.assert_array_equal(z,[10.,20.])

    def test_rightmost_pixel_center_is_inside(self):
        raster=np.array([[10.,20.],[30.,40.]])
        z,_=sample_raster_nearest(raster,from_origin(0,2,1,1),np.array([1.5]),np.array([.5]),'EPSG:32645','EPSG:32645',-9999.)
        np.testing.assert_array_equal(z,[40.])

if __name__=='__main__': unittest.main()
