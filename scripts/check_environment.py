"""Exercise the modeling stack using synthetic data, without downloading datasets.

Run after ``conda activate mc-base`` or through ``conda run -n mc-base`` so
Windows native libraries receive their required DLL and GDAL/PROJ paths.
All generated fixtures are synthetic and are written under
output/environment-check; they are not competition results.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "environment-check"
SEED = 2026


def check_imports() -> dict:
    """Import native dependencies as well as high-level Python interfaces."""
    packages = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels.api",
        "matplotlib": "matplotlib",
        "seaborn": "seaborn",
        "openpyxl": "openpyxl",
        "pyarrow": "pyarrow",
        "PyYAML": "yaml",
        "requests": "requests",
        "tqdm": "tqdm",
        "jupyterlab": "jupyterlab",
        "ipykernel": "ipykernel",
        "xarray": "xarray",
        "netCDF4": "netCDF4",
        "h5netcdf": "h5netcdf",
        "dask": "dask.array",
        "bottleneck": "bottleneck",
        "geopandas": "geopandas",
        "rasterio": "rasterio",
        "rioxarray": "rioxarray",
        "pyproj": "pyproj",
        "shapely": "shapely",
        "cartopy": "cartopy",
    }
    versions = {}
    for package, module in packages.items():
        importlib.import_module(module)
        versions[package] = importlib.metadata.version(package)
    return versions


def check_modeling_and_tables() -> dict:
    """Verify Excel/Parquet IO, a fitted sklearn pipeline, and statsmodels."""
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_absolute_error
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(SEED)
    features = rng.normal(size=(128, 3))
    target = features @ np.array([2.0, -0.5, 1.0]) + rng.normal(0, 0.01, 128)
    table = pd.DataFrame(features, columns=["feature_a", "feature_b", "feature_c"])
    table["target"] = target

    parquet_path = OUTPUT_DIR / "synthetic_table.parquet"
    excel_path = OUTPUT_DIR / "synthetic_table.xlsx"
    table.to_parquet(parquet_path, index=False)
    table.to_excel(excel_path, index=False)
    pd.testing.assert_frame_equal(table, pd.read_parquet(parquet_path))
    pd.testing.assert_frame_equal(table, pd.read_excel(excel_path))

    # This chronological split is only a package integration check. Real event
    # splits will be defined after auditing the competition data and labels.
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(features[:96], target[:96])
    mae = float(mean_absolute_error(target[96:], model.predict(features[96:])))
    assert mae < 0.1, f"Synthetic regression failed: MAE={mae}"
    fit = sm.OLS(target, sm.add_constant(features)).fit()
    assert fit.rsquared > 0.99
    return {"synthetic_holdout_mae": mae, "synthetic_ols_r_squared": float(fit.rsquared)}


def check_meteorological_data() -> dict:
    """Write HDF5 NetCDF and decode through two backends, including Unicode paths."""
    import numpy as np
    import pandas as pd
    import xarray as xr
    from netCDF4 import Dataset
    from xarray.backends import NetCDF4DataStore

    rng = np.random.default_rng(SEED)
    values = rng.normal(273.15, 2.0, size=(48, 3, 4))
    dataset = xr.Dataset(
        {"air_temperature": (("time", "latitude", "longitude"), values)},
        coords={
            "time": pd.date_range("2026-01-01", periods=48, freq="h"),
            "latitude": [28.3, 28.4, 28.5],
            "longitude": [85.2, 85.3, 85.4, 85.5],
        },
        attrs={"description": "Synthetic environment check; not observations", "time_zone": "UTC"},
    )
    dataset.air_temperature.attrs["units"] = "K"
    path = OUTPUT_DIR / "synthetic_meteorology.nc"
    dataset.to_netcdf(path, engine="h5netcdf")
    # Reading native netCDF4 from bytes avoids its Windows narrow-path API.
    memory_dataset = Dataset('in_memory_environment_check', memory=path.read_bytes())
    with xr.open_dataset(NetCDF4DataStore(memory_dataset), chunks={"time": 12}) as loaded:
        assert loaded.air_temperature.chunks is not None
        daily = loaded.air_temperature.resample(time="1D").mean().compute()
        assert daily.shape == (2, 3, 4)
        np.testing.assert_allclose(daily.values, values.reshape(2, 24, 3, 4).mean(axis=1))
    with xr.open_dataset(path, engine="h5netcdf") as loaded:
        xr.testing.assert_allclose(dataset, loaded.load())
    return {"netcdf_roundtrip": True, "dask_daily_aggregation": True, "daily_shape": [2, 3, 4]}


def check_geospatial_data() -> dict:
    """Exercise PROJ/GDAL: vector IO, spatial joins, and raster reprojection."""
    import geopandas as gpd
    import numpy as np
    import rasterio
    import rioxarray
    from pyproj import Transformer
    from rasterio.transform import from_origin
    from shapely.geometry import Point

    longitude, latitude = 85.3, 28.4
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    easting, northing = transformer.transform(longitude, latitude)
    sites = gpd.GeoDataFrame(
        {"site_id": [1], "synthetic": [True]},
        geometry=[Point(longitude, latitude)],
        crs="EPSG:4326",
    )
    projected = sites.to_crs("EPSG:32645")
    np.testing.assert_allclose([projected.geometry.x.iloc[0], projected.geometry.y.iloc[0]], [easting, northing])
    zones = gpd.GeoDataFrame({"zone_id": [1]}, geometry=projected.geometry.buffer(100), crs=projected.crs)
    joined = gpd.sjoin(projected, zones, predicate="within")
    assert len(joined) == 1

    vector_path = OUTPUT_DIR / "synthetic_sites.gpkg"
    projected.to_file(vector_path, layer="sites", driver="GPKG", mode="w")
    restored = gpd.read_file(vector_path, layer="sites")
    assert len(restored) == 1 and restored.crs.to_epsg() == 32645

    raster_path = OUTPUT_DIR / "synthetic_dem.tif"
    dem = np.arange(20, dtype="float32").reshape(4, 5) + 4000
    with rasterio.open(
        raster_path, "w", driver="GTiff", width=5, height=4, count=1,
        dtype="float32", crs="EPSG:32645", nodata=-9999.0,
        transform=from_origin(easting - 60, northing + 60, 30, 30),
    ) as destination:
        destination.write(dem, 1)
    with rioxarray.open_rasterio(raster_path, masked=True) as raster:
        np.testing.assert_allclose(raster.values[0], dem)
        geographic = raster.rio.reproject("EPSG:4326")
        assert geographic.rio.crs.to_epsg() == 4326
        assert np.isfinite(geographic.values).any()
    return {
        "vector_gpkg_roundtrip": True,
        "spatial_join": True,
        "raster_geotiff_roundtrip": True,
        "raster_reprojection": True,
        "gdal_version": rasterio.__gdal_version__,
    }


def check_plotting() -> dict:
    """Render a scientific plot and Cartopy map without online basemap data."""
    import cartopy.crs as ccrs
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    figure = plt.figure(figsize=(9, 3.5), layout="constrained")
    series = figure.add_subplot(1, 2, 1)
    hours = np.arange(48)
    series.plot(hours, 273.15 + 2 * np.sin(hours * np.pi / 12))
    series.set(xlabel="Hour", ylabel="Temperature (K)", title="Synthetic meteorological series")
    map_axes = figure.add_subplot(1, 2, 2, projection=ccrs.PlateCarree())
    map_axes.set_extent([85.1, 85.6, 28.2, 28.6], crs=ccrs.PlateCarree())
    map_axes.scatter([85.3], [28.4], transform=ccrs.PlateCarree(), color="tab:red")
    map_axes.gridlines(draw_labels=True)
    map_axes.set_title("Synthetic site / coordinate check")
    figure.suptitle("Environment check - synthetic data only", fontsize=11)
    for extension in ("png", "pdf"):
        figure.savefig(OUTPUT_DIR / f"synthetic_plot.{extension}", dpi=150)
    plt.close(figure)
    return {"png_export": True, "pdf_export": True, "cartopy_render": True}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "random_seed": SEED,
        "synthetic_data_only": True,
        "checks": {},
    }
    checks = {
        "imports": check_imports,
        "modeling_and_tables": check_modeling_and_tables,
        "meteorological_data": check_meteorological_data,
        "geospatial_data": check_geospatial_data,
        "plotting": check_plotting,
    }
    for name, check in checks.items():
        try:
            details = check()
            report["checks"][name] = {"status": "passed", "details": details}
            print(f"PASS {name}", flush=True)
        except Exception:
            error = traceback.format_exc()
            report["checks"][name] = {"status": "failed", "error": error}
            print(f"FAIL {name}\n{error}", flush=True)
    report["passed"] = all(check["status"] == "passed" for check in report["checks"].values())
    report_path = OUTPUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {report_path}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
