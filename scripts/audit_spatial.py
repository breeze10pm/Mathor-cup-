"""Reproducible spatial attachment audit; no model fitting. Run using mc-base conda."""

from __future__ import annotations
import json, re, zipfile, subprocess, hashlib, sys, warnings
from pathlib import Path, PurePosixPath
from collections import Counter
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds
from rasterio.features import geometry_mask
from shapely.geometry import box, mapping
from shapely.validation import explain_validity
from pyproj import CRS, Geod, Transformer
import xarray as xr
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import xml.etree.ElementTree as ET
from project_runtime import find_archive_tar, open_hdf5_netcdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/data_audit/spatial"
EXTRACT = ROOT / "data/extracted/spatial"
OUT.mkdir(parents=True, exist_ok=True)
EXTRACT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "SimHei",
            "DejaVu Sans",
        ],
        "axes.unicode_minus": False,
        "figure.dpi": 130,
    }
)


def safe_member(name, dest):
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or ":" in name:
        raise ValueError(f"Unsafe archive member: {name}")
    target = (dest / str(p)).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise ValueError(name)
    return target


def decode_tar(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("Unable to decode archive names")


def unpack(n):
    arc = next((ROOT / "data/附件").glob(f"（{n}）*"))
    dest = EXTRACT / f"attachment_{n}"
    dest.mkdir(parents=True, exist_ok=True)
    if arc.suffix.lower() == ".zip":
        with zipfile.ZipFile(arc) as z:
            for info in z.infolist():
                target = safe_member(info.filename, dest)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif not target.exists() or target.stat().st_size != info.file_size:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, target.open("wb") as dst:
                        import shutil

                        shutil.copyfileobj(src, dst)
            listing = z.namelist()
    else:
        tar = find_archive_tar()
        result = subprocess.run([tar, "-tf", str(arc)], capture_output=True)
        if result.returncode:
            raise RuntimeError(
                "The discovered tar cannot read this RAR. Put a RAR-capable bsdtar on PATH; see README.md. "
                + result.stderr.decode("utf-8", errors="replace")
            )
        listing = [x.strip() for x in decode_tar(result.stdout).splitlines() if x.strip()]
        for member in listing:
            safe_member(member, dest)
        marker = dest / ".extracted.json"
        if not marker.exists():
            subprocess.run([tar, "-xf", str(arc), "-C", str(dest)], check=True, capture_output=True)
            marker.write_text(
                json.dumps({"archive_bytes": arc.stat().st_size, "members": len(listing)}),
                encoding="utf-8",
            )
    return arc, dest, listing


def clean(v):
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, np.ndarray):
        return clean(v.tolist())
    if isinstance(v, (datetime, pd.Timestamp)):
        return str(v)
    if isinstance(v, Path):
        return str(v.relative_to(ROOT))
    if pd.isna(v):
        return None
    return v


def savejson(name, data):
    (OUT / name).write_text(
        json.dumps(clean(data), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def csv(name, rows):
    pd.DataFrame(rows).to_csv(OUT / name, index=False, encoding="utf-8-sig")


def field_audit(g, source):
    rows = []
    for col in g.columns.drop("geometry"):
        s = g[col]
        rows.append(
            dict(
                source=source,
                field=col,
                dtype=str(s.dtype),
                missing=int(s.isna().sum()),
                unique=int(s.nunique()),
                examples=" | ".join(str(x) for x in s.dropna().unique()[:12]),
            )
        )
    return rows


def vector_audit(g, source):
    return dict(
        source=source,
        records=len(g),
        crs=str(g.crs),
        bounds=g.total_bounds,
        geometry_types=g.geom_type.value_counts().to_dict(),
        invalid=int((~g.is_valid).sum()),
        empty=int(g.is_empty.sum()),
        null_geometry=int(g.geometry.isna().sum()),
        duplicates_geometry=int(g.geometry.to_wkb().duplicated().sum()),
    )


def raster_header(src, path):
    wgs = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    return dict(
        file=str(path.relative_to(ROOT)),
        crs=str(src.crs),
        width=src.width,
        height=src.height,
        count=src.count,
        dtype=src.dtypes[0],
        nodata=src.nodata,
        resolution=src.res,
        bounds=list(src.bounds),
        bounds_epsg4326=wgs,
        units=CRS(src.crs).axis_info[0].unit_name,
        tags=src.tags(),
    )


def pixel_areas(src):
    """Per-row single-cell area, ellipsoidal for degree grids; planar for UTM."""
    if CRS(src.crs).is_projected:
        return np.full(src.height, abs(src.transform.a * src.transform.e))
    geod = CRS(src.crs).get_geod()
    x = src.bounds.left
    dx = src.res[0]
    result = []
    for r in range(src.height):
        yt = src.bounds.top - r * src.res[1]
        yb = yt - src.res[1]
        a, _ = geod.polygon_area_perimeter([x, x + dx, x + dx, x], [yt, yt, yb, yb])
        result.append(abs(a))
    return np.array(result)


def full_raster(src, path, with_area=False):
    # A single TIFF at a time, no approximation or downsampling for these statistics.
    arr = src.read(1, masked=True)
    valid = (~np.ma.getmaskarray(arr)) & np.isfinite(arr.data)
    values = arr.data[valid]
    info = raster_header(src, path)
    info.update(
        statistic_scope="all band-1 pixels; nodata mask plus finite check",
        pixels=arr.size,
        valid_pixels=int(valid.sum()),
        missing_pixels=int((~valid).sum()),
        missing_fraction=float((~valid).mean()),
        min=float(values.min()) if values.size else None,
        max=float(values.max()) if values.size else None,
        mean=float(values.mean(dtype=np.float64)) if values.size else None,
    )
    if with_area:
        areas = pixel_areas(src)
        info.update(
            valid_area_km2=float(np.sum(valid.sum(axis=1) * areas) / 1e6),
            missing_area_km2=float(np.sum((~valid).sum(axis=1) * areas) / 1e6),
            area_method="ellipsoidal row-wise pixel area"
            if CRS(src.crs).is_geographic
            else "projected planar pixel area",
        )
    return info, arr, valid


def savefig(fig, name):
    fig.savefig(OUT / (name + ".png"), bbox_inches="tight")
    fig.savefig(OUT / (name + ".svg"), bbox_inches="tight")
    plt.close(fig)


def joincounts(g, cols):
    return [
        dict(field=c, value="<MISSING>" if pd.isna(v) else str(v), count=int(n))
        for c in cols
        for v, n in g[c].value_counts(dropna=False).items()
    ]


def main():
    extracted = {}
    inventories = []
    for n in (3, 4, 5, 6, 7, 8):
        arc, dest, members = unpack(n)
        extracted[n] = dest
        with arc.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        inventories.append(
            dict(
                attachment=n,
                archive=arc.name,
                bytes=arc.stat().st_size,
                sha256=digest,
                members=len(members),
                suffix_counts=dict(
                    Counter(Path(x).suffix.lower() for x in members if Path(x).suffix)
                ),
            )
        )
    savejson("archive_inventory.json", inventories)
    hist = gpd.read_file(next(extracted[6].rglob("*.shp")))
    pop = gpd.read_file(next(extracted[8].rglob("*.shp")))
    fields = field_audit(hist, "attachment_6") + field_audit(pop, "attachment_8")
    vectors = [vector_audit(hist, "attachment_6"), vector_audit(pop, "attachment_8")]
    distributions = joincounts(
        hist, ["flag", "类型", "规模", "频率", "河流", "有无_Fan", "解译Time", "影像Time"]
    )
    csv("historical_distributions.csv", distributions)
    hist.drop(columns="geometry").to_csv(
        OUT / "historical_attributes.csv", index=False, encoding="utf-8-sig"
    )
    pop.drop(columns="geometry").to_csv(
        OUT / "population_attributes.csv", index=False, encoding="utf-8-sig"
    )
    ds = open_hdf5_netcdf(next(extracted[4].glob("*.nc")))
    ncvars = []
    for k in ds.variables:
        a = ds[k].values
        finite = np.isfinite(a)
        vals = a[finite]
        row = dict(
            variable=k,
            dims=str(ds[k].dims),
            shape=str(a.shape),
            dtype=str(a.dtype),
            cells=a.size,
            valid=int(finite.sum()),
            missing=int((~finite).sum()),
            min=float(vals.min()) if vals.size else None,
            max=float(vals.max()) if vals.size else None,
            mean=float(vals.mean(dtype=np.float64)) if vals.size else None,
            units=ds[k].attrs.get("units"),
            attributes=ds[k].attrs,
            encoding_fillvalue=ds[k].encoding.get("_FillValue"),
        )
        if a.ndim == 2:
            gm = ds.glacier_mask.values == 1
            glvals = a[gm & finite]
            row.update(
                glacier_mask_valid=int((gm & finite).sum()),
                glacier_mask_cells=int(gm.sum()),
                glacier_min=float(glvals.min()) if glvals.size else None,
                glacier_max=float(glvals.max()) if glvals.size else None,
            )
        ncvars.append(row)
    nc_crs = CRS.from_wkt(ds.spatial_ref.attrs["crs_wkt"])
    nc_bounds = (
        float(ds.x.min() - 15),
        float(ds.y.min() - 15),
        float(ds.x.max() + 15),
        float(ds.y.max() + 15),
    )
    nc_wgs = transform_bounds(nc_crs, "EPSG:4326", *nc_bounds, densify_pts=21)
    ncmeta = dict(
        attributes=ds.attrs,
        crs=nc_crs.to_string(),
        bounds=nc_bounds,
        bounds_epsg4326=nc_wgs,
        grid_resolution_m=[
            float(abs(np.diff(ds.x.values)[0])),
            float(abs(np.diff(ds.y.values)[0])),
        ],
        variables=ncvars,
        glacier_mask_counts=dict(Counter(str(x) for x in ds.glacier_mask.values.ravel())),
        temporal_interpretation="No time dimension. Velocities are 2014–2024 climatology with 2018-01-01 intercept; bilinearly resampled to 30 m. Not a real-time pre-event series.",
    )
    savejson("netcdf_audit.json", ncmeta)
    csv(
        "netcdf_variables.csv",
        [{**x, "attributes": json.dumps(x["attributes"], ensure_ascii=False)} for x in ncvars],
    )
    docs = []
    for path in extracted[3].rglob("*.docx"):
        with zipfile.ZipFile(path) as z:
            tree = ET.fromstring(z.read("word/document.xml"))
            docs.append(
                "\n".join(
                    "".join(p.itertext())
                    for p in tree.findall(
                        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                    )
                )
            )
    (OUT / "attachment3_document_text.txt").write_text("\n\n".join(docs), encoding="utf-8")
    rgi = {}
    invalid_details = []
    rgi_dates = []
    for path in extracted[3].rglob("*.shp"):
        g = gpd.read_file(path)
        rgi[path.stem] = g
        vectors.append(vector_audit(g, "attachment_3/" + path.stem))
        fields += field_audit(g, "attachment_3/" + path.stem)
        g.drop(columns="geometry").to_csv(
            OUT / (path.stem + "_attributes.csv"), index=False, encoding="utf-8-sig"
        )
        for idx, row in g[~g.is_valid].iterrows():
            invalid_details.append(
                dict(
                    source=path.stem,
                    row_index=int(idx),
                    reason=explain_validity(row.geometry),
                    identifier=row.get("RGIId", row.get("rgi_id", None)),
                )
            )
        for col in ("BgnDate", "EndDate", "src_date"):
            if col in g:
                rgi_dates.extend(
                    dict(source=path.stem, field=col, value=str(value), count=int(count))
                    for value, count in g[col].value_counts(dropna=False).items()
                )
    csv("invalid_geometry_details.csv", invalid_details)
    csv("glacier_inventory_date_counts.csv", rgi_dates)
    csv("vector_fields.csv", fields)
    savejson("vector_audit.json", vectors)
    raster_records = []
    print("Scanning all attachment-3 TIFF pixels...", flush=True)
    for path in sorted(extracted[3].rglob("*.tif")):
        with rasterio.open(path) as src:
            info, _, _ = full_raster(src, path)
            period = re.search(r"(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)", str(path))
            info.update(
                attachment=3, period_start=period[1], period_end=period[2], product=path.parent.name
            )
            raster_records.append(info)
    csv(
        "glacier_raster_inventory.csv",
        [{**x, "tags": json.dumps(x["tags"], ensure_ascii=False)} for x in raster_records],
    )
    periods = (
        pd.DataFrame(raster_records)
        .groupby(["period_start", "period_end", "product"])
        .agg(
            files=("file", "count"),
            pixels=("pixels", "sum"),
            valid_pixels=("valid_pixels", "sum"),
            missing_pixels=("missing_pixels", "sum"),
            min=("min", "min"),
            max=("max", "max"),
        )
        .reset_index()
    )
    periods.to_csv(OUT / "glacier_period_summary.csv", index=False, encoding="utf-8-sig")
    # These overlapping tile totals are pixel counts, not a union of glacier area.
    lc_records = []
    classrows = []
    lcarrays = {}
    lc_coverage = []
    source_xx, source_yy = np.meshgrid(ds.x.values, ds.y.values)
    source_lng, source_lat = Transformer.from_crs(nc_crs, 4326, always_xy=True).transform(
        source_xx, source_yy
    )
    grids = []
    for path in sorted(extracted[5].glob("*.tif")):
        with rasterio.open(path) as src:
            info, arr, valid = full_raster(src, path, with_area=True)
            year = int(re.search(r"20\d{2}", path.name)[0])
            info.update(attachment=5, year=year)
            lc_records.append(info)
            lcarrays[year] = arr.data
            grids.append((src.crs.to_string(), src.width, src.height, tuple(src.transform)))
            historical_xy = gpd.GeoDataFrame(
                geometry=gpd.points_from_xy(
                    pd.to_numeric(hist.x_coord), pd.to_numeric(hist.y_coord)
                ),
                crs=hist.crs,
            ).to_crs(src.crs)
            hist_samples = np.ma.concatenate(
                list(src.sample([(p.x, p.y) for p in historical_xy.geometry], masked=True))
            )
            sr, sc = rasterio.transform.rowcol(
                src.transform, source_lng.ravel(), source_lat.ravel()
            )
            sr = np.array(sr)
            sc = np.array(sc)
            inbounds = (sr >= 0) & (sr < src.height) & (sc >= 0) & (sc < src.width)
            usable = np.zeros(len(sr), dtype=bool)
            usable[inbounds] = valid[sr[inbounds], sc[inbounds]]
            gmflat = (ds.glacier_mask.values == 1).ravel()
            lc_coverage.append(
                dict(
                    year=year,
                    historical_attribute_xy_valid=int(
                        ((~np.ma.getmaskarray(hist_samples)) & np.isfinite(hist_samples.data)).sum()
                    ),
                    historical_records=len(hist),
                    source_grid_cells=len(sr),
                    source_grid_valid=int(usable.sum()),
                    glacier_mask_cells=int(gmflat.sum()),
                    glacier_mask_cells_valid=int((gmflat & usable).sum()),
                    method="historical attribute xy and every 30 m NetCDF pixel center; nearest class lookup",
                )
            )
            areas = pixel_areas(src)
            for code in np.unique(arr.data):
                sel = arr.data == code
                classrows.append(
                    dict(
                        year=year,
                        code=int(code),
                        pixels=int(sel.sum()),
                        fraction_of_full_grid=float(sel.mean()),
                        area_km2=float(np.sum(sel.sum(axis=1) * areas) / 1e6),
                        is_nodata=bool(code == src.nodata),
                        class_label="nodata"
                        if code == src.nodata
                        else "unprovided; retain numeric code",
                    )
                )
    savejson("landcover_audit.json", lc_records)
    csv("landcover_class_counts.csv", classrows)
    csv("landcover_spatial_coverage.csv", lc_coverage)
    assert all(g[:3] == grids[0][:3] for g in grids), "Land-cover CRS or grid shapes differ"
    from affine import Affine

    reference_transform = Affine(*grids[0][3][:6])
    corner_diff = max(
        max(
            abs((Affine(*g[3][:6]) * (c, r))[j] - (reference_transform * (c, r))[j])
            / abs(grids[0][3][0 if j == 0 else 4])
            for j in (0, 1)
        )
        for g in grids
        for c, r in [(0, 0), (grids[0][1], 0), (0, grids[0][2]), (grids[0][1], grids[0][2])]
    )
    assert corner_diff < 1e-6, (
        "Land-cover grids differ by >=1e-6 pixel; transitions require explicit alignment"
    )
    transitions = []
    for y in (2020, 2021, 2022):
        a = lcarrays[y]
        b = lcarrays[y + 1]
        valid = (a != 0) & (b != 0)
        codes, counts = np.unique((a[valid].astype(np.int32) * 256 + b[valid]), return_counts=True)
        transitions.extend(
            dict(
                year_from=y,
                year_to=y + 1,
                code_from=int(k // 256),
                code_to=int(k % 256),
                pixels=int(n),
            )
            for k, n in zip(codes, counts)
        )
    csv("landcover_transitions.csv", transitions)
    dempath = next(extracted[7].glob("*.tif"))
    with rasterio.open(dempath) as src:
        deminfo, dem, demvalid = full_raster(src, dempath, with_area=True)
        deminfo["attachment"] = 7
        deminfo["approx_cell_width_m_at_center"] = abs(
            CRS(src.crs)
            .get_geod()
            .inv(
                src.bounds.left,
                np.mean([src.bounds.bottom, src.bounds.top]),
                src.bounds.left + src.res[0],
                np.mean([src.bounds.bottom, src.bounds.top]),
            )[2]
        )
        deminfo["approx_cell_height_m_at_center"] = abs(
            CRS(src.crs)
            .get_geod()
            .inv(
                src.bounds.left, src.bounds.bottom, src.bounds.left, src.bounds.bottom + src.res[1]
            )[2]
        )
        dem_bounds = src.bounds
        dem_transform = src.transform
        dem_box = box(*src.bounds)
        hg = hist.to_crs(src.crs)
        xy = gpd.GeoDataFrame(
            hist[["Code"]].copy(),
            geometry=gpd.points_from_xy(pd.to_numeric(hist.x_coord), pd.to_numeric(hist.y_coord)),
            crs=hist.crs,
        ).to_crs(src.crs)
        metric_hg = hist.to_crs(32645)
        metric_xy = xy.to_crs(32645)
        coverage = []
        for i, row in hg.iterrows():
            mask = geometry_mask(
                [mapping(row.geometry)],
                out_shape=dem.shape,
                transform=src.transform,
                invert=True,
                all_touched=False,
            )
            pt = xy.geometry.loc[i]
            inside = dem_box.covers(pt)
            rr, cc = src.index(pt.x, pt.y)
            validxy = (
                bool(demvalid[rr, cc])
                if inside and 0 <= rr < src.height and 0 <= cc < src.width
                else False
            )
            coverage.append(
                dict(
                    Code=row.Code,
                    type=row["类型"],
                    polygon_intersects_dem=bool(row.geometry.intersects(dem_box)),
                    polygon_fully_in_dem_bounds=bool(dem_box.covers(row.geometry)),
                    dem_pixel_centers_in_polygon=int(mask.sum()),
                    dem_valid_pixel_centers_in_polygon=int((mask & demvalid).sum()),
                    attribute_xy_in_dem_bounds=inside,
                    attribute_xy_valid_dem=validxy,
                    xy_inside_own_polygon=bool(row.geometry.covers(pt)),
                    xy_distance_to_own_polygon_m=float(
                        metric_hg.geometry.loc[i].distance(metric_xy.geometry.loc[i])
                    ),
                    attribute_xy_dem_m=float(dem.data[rr, cc]) if validxy else None,
                )
            )
        csv("historical_dem_coverage.csv", coverage)
        # Test every 30 m glacier-mask pixel centre, transformed to the DEM CRS.
        xx, yy = np.meshgrid(ds.x.values, ds.y.values)
        lng, lat = Transformer.from_crs(nc_crs, src.crs, always_xy=True).transform(xx, yy)
        rr, cc = rasterio.transform.rowcol(src.transform, lng.ravel(), lat.ravel())
        rr = np.asarray(rr).reshape(xx.shape)
        cc = np.asarray(cc).reshape(xx.shape)
        inbounds = (rr >= 0) & (rr < src.height) & (cc >= 0) & (cc < src.width)
        cellvalid = np.zeros_like(inbounds)
        cellvalid[inbounds] = demvalid[rr[inbounds], cc[inbounds]]
        gm = ds.glacier_mask.values == 1
        sourcecov = dict(
            source_grid_cells=int(xx.size),
            source_grid_cells_in_dem_bounds=int(inbounds.sum()),
            source_grid_cells_with_valid_dem=int(cellvalid.sum()),
            glacier_mask_cells=int(gm.sum()),
            glacier_mask_cells_in_dem_bounds=int((gm & inbounds).sum()),
            glacier_mask_cells_with_valid_dem=int((gm & cellvalid).sum()),
            coordinate_method="every NetCDF 30 m pixel center transformed EPSG:32645 to DEM EPSG:4326, nearest DEM cell",
            source_center_epsg4326=list(
                Transformer.from_crs(nc_crs, 4326, always_xy=True).transform(
                    float(ds.x.mean()), float(ds.y.mean())
                )
            ),
        )
        attrs = next(g for name, g in rgi.items() if name.startswith("JilongFlood_Buffer"))
        official_source = attrs[["Longitude", "Latitude"]].iloc[0].to_dict()
        orow, ocol = src.index(official_source["Longitude"], official_source["Latitude"])
        sourcecov["official_buffer_center_epsg4326"] = official_source
        sourcecov["official_buffer_center_valid_dem"] = bool(
            0 <= orow < src.height and 0 <= ocol < src.width and demvalid[orow, ocol]
        )
    savejson("dem_audit.json", deminfo)
    demxml = ET.parse(extracted[7] / "DEM.tif.xml").getroot()
    demdates = [
        dict(tag=x.tag, value=x.text)
        for x in demxml.iter()
        if x.text and any(t in x.tag.lower() for t in ("date", "time"))
    ]
    savejson(
        "dem_metadata_dates.json",
        dict(
            entries=demdates,
            interpretation="ArcGIS creation/sync/modification metadata; not a demonstrated acquisition time or pre-event surface",
        ),
    )
    savejson("dem_source_coverage.json", sourcecov)
    cov = pd.DataFrame(coverage)
    covsummary = {
        c: int(cov[c].sum())
        for c in [
            "polygon_intersects_dem",
            "polygon_fully_in_dem_bounds",
            "attribute_xy_in_dem_bounds",
            "attribute_xy_valid_dem",
            "xy_inside_own_polygon",
        ]
    }
    covsummary["polygons_with_any_valid_dem_pixel_center"] = int(
        (cov.dem_valid_pixel_centers_in_polygon > 0).sum()
    )
    covsummary["records"] = len(hist)
    covsummary["outside_attribute_xy_distances_m"] = cov.loc[
        ~cov.xy_inside_own_polygon, ["Code", "xy_distance_to_own_polygon_m"]
    ].to_dict("records")
    savejson("historical_dem_coverage_summary.json", covsummary)
    # Scope is evidence auditing, not source attribution or event prediction.
    time_notes = dict(
        historical_interpretation_date=dict(
            field="解译Time",
            meaning="stored date field named 解译Time; business meaning unconfirmed; not an event label",
            counts=hist["解译Time"].astype(str).value_counts().to_dict(),
        ),
        historical_image_date=dict(
            field="影像Time",
            meaning="stored date field named 影像Time; acquisition/reference interpretation unconfirmed",
            counts=hist["影像Time"].astype(str).value_counts().to_dict(),
        ),
        event_date_available=False,
        netcdf=ncmeta["temporal_interpretation"],
        glacier_dhdt_periods=periods[["period_start", "period_end"]]
        .drop_duplicates()
        .to_dict("records"),
        dem_date="XML records Clip processing at 20260826 171843 with no timezone; not an acquisition timestamp or proof of pre-event terrain",
        population="County-level census fields 合计 and 人口数 have different values; exact definitions and reason for difference unconfirmed; local distribution absent",
        rgi_dates="RGI date-like fields are stored values; source/date semantics and sentinel definitions require upstream dictionaries; not event labels",
    )
    savejson("time_semantics.json", time_notes)
    # Figure 1: context and local source coverage, with legends kept outside the data.
    colors = {
        "降雨型": "#d07914",
        "冰水混合型": "#168c78",
        "冰雪融水型": "#346bb0",
        "冰湖溃决型": "#a33c87",
    }
    fig, axs = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.05, 1]})
    ax = axs[0]
    pop.to_crs(4326).boundary.plot(ax=ax, color="#aaaaaa", linewidth=0.8)
    for typ, col in colors.items():
        hist.to_crs(4326).query("类型 == @typ").plot(
            ax=ax, color=col, edgecolor=col, alpha=0.65, linewidth=0.45
        )
    gpd.GeoSeries([dem_box], crs=4326).boundary.plot(ax=ax, color="#123d75", linewidth=1.8)
    gpd.GeoSeries([box(*nc_wgs)], crs=4326).boundary.plot(ax=ax, color="#cd2239", linewidth=2)
    ax.scatter(
        [official_source["Longitude"]],
        [official_source["Latitude"]],
        marker="*",
        s=110,
        color="#cd2239",
        zorder=6,
    )
    ax.set(
        xlim=(85.0, 85.75),
        ylim=(28.2, 29.05),
        xlabel="经度 (°E)",
        ylabel="纬度 (°N)",
        title="历史灾害多边形与DEM / 冰崩源区覆盖",
    )
    handles = [
        Patch(facecolor=c, label=f"{t} ({int((hist['类型'] == t).sum())})")
        for t, c in colors.items()
    ]
    handles += [
        Line2D([0], [0], color="#123d75", lw=2, label="附件7 DEM边界"),
        Line2D([0], [0], color="#cd2239", lw=2, label="附件4 30m网格边界"),
        Line2D(
            [0],
            [0],
            marker="*",
            color="#cd2239",
            linestyle="None",
            markersize=9,
            label="附件3官方200km缓冲中心",
        ),
        Line2D([0], [0], color="#aaaaaa", lw=1, label="县级人口面边界 (仅作参照)"),
    ]
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0, -0.13),
        ncol=2,
        fontsize=8,
        framealpha=0.95,
    )
    ax.grid(alpha=0.2)
    ax = axs[1]
    im = ax.imshow(
        dem,
        extent=[dem_bounds.left, dem_bounds.right, dem_bounds.bottom, dem_bounds.top],
        cmap="terrain",
        origin="upper",
        vmin=1500,
        vmax=7500,
    )
    ax.contour(
        lng,
        lat,
        (ds.glacier_mask.values == 1).astype(float),
        levels=[0.5],
        colors=["#cd2239"],
        linewidths=1.2,
    )
    ax.scatter(
        [official_source["Longitude"]],
        [official_source["Latitude"]],
        marker="*",
        s=130,
        color="#cd2239",
        edgecolor="white",
        zorder=5,
    )
    ax.set(
        xlim=(nc_wgs[0] - 0.008, nc_wgs[2] + 0.008),
        ylim=(nc_wgs[1] - 0.008, nc_wgs[3] + 0.008),
        xlabel="经度 (°E)",
        ylabel="纬度 (°N)",
        title="源区细图：附件7 DEM与附件4冰川掩膜",
    )
    ax.legend(
        handles=[
            Line2D([0], [0], color="#cd2239", lw=1.5, label="glacier_mask = 1 边界"),
            Line2D(
                [0],
                [0],
                marker="*",
                color="#cd2239",
                linestyle="None",
                markersize=9,
                label="官方缓冲中心",
            ),
        ],
        loc="upper right",
        fontsize=8,
    )
    fig.colorbar(im, ax=ax, label="附件7高程 (m)", fraction=0.04, pad=0.03)
    ax.grid(alpha=0.2)
    fig.suptitle("空间审计：覆盖不等于事件关联；历史84条记录均为Polygon", fontsize=13)
    fig.tight_layout()
    savefig(fig, "spatial_coverage")
    # Figure 2: numeric land-cover classes; no unsupported semantic labels.
    lcdf = pd.DataFrame(classrows)
    table = lcdf[~lcdf.is_nodata].pivot(index="year", columns="code", values="area_km2")
    fig, ax = plt.subplots(figsize=(10, 5))
    table.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.65)
    ax.set(
        xlabel="年份",
        ylabel="各数值类码覆盖面积 (km²；椭球面积)",
        title="附件5土地覆盖：保留原始类码，附件未附类别释义",
    )
    ax.legend(title="原始类码", loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=9)
    ax.tick_params(axis="x", rotation=0)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    savefig(fig, "landcover_codes")
    # Figure 3: native 30 m glacier grid; velocities are temporal climatology.
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.6))
    for ax, k, title, cmap in zip(
        axs,
        ["dem", "thickness", "v"],
        ["高程 (m)", "冰厚 (m)", "2014–2024气候态速度 (m/年)"],
        ["terrain", "Blues", "magma"],
    ):
        arr = ds[k].values.copy()
        arr[~gm] = np.nan
        im = ax.imshow(
            arr,
            extent=[nc_bounds[0], nc_bounds[2], nc_bounds[1], nc_bounds[3]],
            origin="upper",
            cmap=cmap,
        )
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set(title=title, xlabel="UTM45N东向坐标 (m)", ylabel="北向坐标 (m)")
        ax.ticklabel_format(style="plain", useOffset=False)
        ax.tick_params(axis="x", rotation=30, labelsize=7)
        ax.tick_params(axis="y", labelsize=7)
    fig.suptitle("附件4：仅显示glacier_mask=1；30m为参考网格，速度经双线性重采样", fontsize=12)
    fig.tight_layout()
    savefig(fig, "glacier_native_grid")
    v_residual = ds.v.values - np.hypot(ds.vx.values, ds.vy.values)
    checks = dict(
        landcover_grid_aligned_within_tolerance=True,
        landcover_max_corner_displacement_pixels=corner_diff,
        landcover_alignment_tolerance_pixels=1e-6,
        all_landcover_frequency_totals_match=all(
            sum(x["pixels"] for x in classrows if x["year"] == y) == lcarrays[y].size
            for y in lcarrays
        ),
        historical_type_total_equals_records=sum(hist["类型"].value_counts()) == len(hist),
        netcdf_velocity_hypotenuse_max_abs_error=float(np.nanmax(np.abs(v_residual))),
        netcdf_velocity_hypotenuse_residual_mean=float(np.nanmean(v_residual)),
        netcdf_velocity_hypotenuse_residual_median=float(np.nanmedian(v_residual)),
        netcdf_velocity_hypotenuse_residual_positive_cells=int((v_residual > 0).sum()),
        netcdf_v_matches_hypotenuse_within_0_001_m_per_year=bool(
            np.nanmax(np.abs(v_residual)) < 0.001
        ),
        netcdf_v_residual_interpretation="Observed source-data discrepancy, not an execution failure. Independent bilinear resampling of speed and components is a plausible explanation (inference, not confirmed). Retain original variables.",
        netcdf_thickness_valid_equals_glacier_mask=bool(
            np.array_equal(np.isfinite(ds.thickness.values), gm)
        ),
        dem_pixel_count_matches_shape=deminfo["pixels"] == deminfo["width"] * deminfo["height"],
        glacier_rasters_read=len(raster_records),
        raster_counts_balance=all(
            x["valid_pixels"] + x["missing_pixels"] == x["pixels"]
            for x in raster_records + lc_records + [deminfo]
        ),
    )
    assert (
        checks["all_landcover_frequency_totals_match"]
        and checks["historical_type_total_equals_records"]
        and checks["dem_pixel_count_matches_shape"]
        and checks["raster_counts_balance"]
    )
    savejson("validation_checks.json", checks)
    ds.close()
    summary = dict(
        generated_utc=datetime.now(timezone.utc).isoformat(),
        scope="Attachments 3–8; local official archives only; no model training",
        raster_scope="All 168 attachment-3 TIFFs, four land-cover TIFFs, one DEM: exact all band-1 pixels; full NetCDF arrays",
        historical=vectors[0],
        population=vectors[1],
        dem=deminfo,
        dem_historical_coverage=covsummary,
        dem_source_coverage=sourcecov,
        landcover=lc_records,
        landcover_spatial_coverage=lc_coverage,
        netcdf=ncmeta,
        glacier_periods=periods.to_dict("records"),
        time_semantics=time_notes,
        validation=checks,
        invalid_geometry_details=invalid_details,
    )
    savejson("spatial_summary.json", summary)
    report(ROOT / "docs/spatial-audit.md", summary, hist, pop, lcdf, vectors, periods)
    print(
        json.dumps(
            clean(
                {
                    "status": "complete",
                    "historical_dem_coverage": covsummary,
                    "source_coverage": sourcecov,
                    "dem": deminfo,
                    "output": OUT,
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


def report(path, s, hist, pop, lcdf, vectors, periods):
    c = s["dem_historical_coverage"]
    d = s["dem"]
    n = s["netcdf"]
    z = s["dem_source_coverage"]
    p = pop.iloc[0]

    def mdtable(frame):
        # Keep report generation independent of optional tabulate.
        columns = list(frame.columns)
        lines = [
            "| " + " | ".join(map(str, columns)) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        lines += [
            "| " + " | ".join(str(x) for x in row) + " |"
            for row in frame.itertuples(index=False, name=None)
        ]
        return "\n".join(lines)

    text = f"""# 附件3—8空间数据审计

范围：官方原始附件，仅EDA、字段语义、覆盖与质量核验，无建模或训练。审计脚本为 `scripts/audit_spatial.py`，固定依赖由项目 `mc-base` 环境提供。重跑：

已按[内嵌元数据复核](spatial-metadata-evidence.md)收紧日期和人口口径用语；官网补充与未决问题见[待确认事项清单](pending-questions.md)。

```powershell
conda run -n mc-base --no-capture-output python scripts/audit_spatial.py
```

原始压缩包只读；解压副本位于 `data/extracted/spatial/attachment_3` 至 `attachment_8`。解压前验证路径，中文RAR列表依次严格尝试UTF-8和GB18030。全部168个冰川变化TIFF、4个土地覆盖TIFF及1个DEM均逐文件读取全部第一波段像元，NetCDF读取全部数组；本报告不存在把抽样估计当全量统计的情形。冰川瓦片可能重叠且UTM/GCS为同一产品不同表达，禁止将其像元数简单相加称为独立冰川面积。

## 关键空间事实

- 历史灾点实际是 **84个Polygon**，CRS={hist.crs}；有效性不合格数={s["historical"]["invalid"]}，空几何数={s["historical"]["empty"]}，重复几何数={s["historical"]["duplicates_geometry"]}。边界={clean(hist.total_bounds)}。多边形可用于空间清单，不等于已提供84次有时间戳的事件。
- DEM为 {d["width"]}×{d["height"]}，{d["crs"]}，像元大小{d["resolution"]} **度**，中心附近约{d["approx_cell_width_m_at_center"]:.2f}×{d["approx_cell_height_m_at_center"]:.2f} m，不能直接把经纬度差当米。边界={d["bounds"]}。
- DEM与历史多边形相交 **{c["polygon_intersects_dem"]}/84**，完全位于矩形范围内 **{c["polygon_fully_in_dem_bounds"]}/84**，至少含一个有效DEM像元中心 **{c["polygons_with_any_valid_dem_pixel_center"]}/84**。属性x/y坐标在DEM范围内且有效 **{c["attribute_xy_valid_dem"]}/84**。这些口径分别衡量面相交、完整覆盖和属性点可采样性，不应互相替代。
- 附件4冰川掩膜像元 **{z["glacier_mask_cells"]}** 个，其中 **{z["glacier_mask_cells_with_valid_dem"]}** 个像元中心落在有效DEM上；附件4全网格{z["source_grid_cells"]}个像元中心中，{z["source_grid_cells_with_valid_dem"]}个有效覆盖。附件3官方200km缓冲中心={z["official_buffer_center_epsg4326"]}，该中心DEM有效={z["official_buffer_center_valid_dem"]}。这是栅格位置的覆盖核验，不是对2026灾害演化过程的识别。
- DEM有效像元{d["valid_pixels"]:,}，缺失{d["missing_pixels"]:,}，缺失率{d["missing_fraction"]:.6%}；有效面积{d["valid_area_km2"]:.3f} km²，缺失面积{d["missing_area_km2"]:.3f} km²（WGS84椭球逐行像元面积）；有效高程{d["min"]:.2f}—{d["max"]:.2f} m，nodata={d["nodata"]}。
- 土地覆盖四年对历史属性点均为83/84有效，但附件4全网格及冰川掩膜内有效像元均为0；不能给冰崩源区补充本附件没有提供的土地覆盖。此处的nodata是缺少覆盖，不是某个类别。

![覆盖核验](../output/data_audit/spatial/spatial_coverage.png)

## 历史记录：标签与日期

类型分布：{hist["类型"].value_counts().to_dict()}。flag分布：{hist["flag"].value_counts().to_dict()}，全部为1，因此仅凭该字段无法构造正负样本；“flag=1”的业务定义未附说明。规模、频率、河流、是否有扇及全部日期分布见 `historical_distributions.csv`。

`解译Time`存储值为{hist["解译Time"].min()}—{hist["解译Time"].max()}，84条全部同日；`影像Time`为{hist["影像Time"].min()}—{hist["影像Time"].max()}。XML只有字段名/类型而无业务定义，并有CalculateField赋日期日志，不能直接称为实际解译/影像采集时间，更**不能当作灾害发生日期**。`Resolution`非空值实际为河流名，不按名称补数值分辨率。`Area`等字段缺少单位字典，保留原值。

属性x/y坐标位于其自身多边形内部或边界上的记录为{c["xy_inside_own_polygon"]}/84；属性点、面质心与沟口等概念不可自动混用。覆盖计算先将历史面及属性点从EPSG:4490转换到DEM的EPSG:4326，再做面与DEM矩形相交/包含和有效像元中心计数。面与DEM关系和属性点采样分别输出于 `historical_dem_coverage.csv`。几何有效不代表灾害清单完整，也不证明各多边形在2026年均发生事件。

2个属性点位于对应多边形外，投影至UTM45N后距离边界分别约3.538 m（Q4XM-JLH-D00245）、0.729 m（Q4XM-PKC-D00179）；这不是将经纬度差直接作为米计算。未据此自动移动坐标或修改面。

## 附件4冰川地形、冰厚与速度

网格138×145，CRS={n["crs"]}，分辨率={n["grid_resolution_m"]} m，经纬度边界={n["bounds_epsg4326"]}。未包含time维。速度来自ITS_LIVE v2.1，元数据明确为**2014—2024年气候态**，采用2018-01-01时间截距；插值方法为bilinear到30m参考网格。30m只是最终参考网格，不证明速度原生观测达到30m，更不能视作临灾实时或逐日速度。冰厚引用元数据中的Farinotti et al. (2019)产品；不能据此创造2026年冰厚实测时间。

缺失按xarray解码后非有限值统计，下面范围为全部有限格点，`glacier_min/max`另列于CSV，便于区分冰川掩膜内与整个矩形网格。

{mdtable(pd.DataFrame(n["variables"]).query('variable not in ["x", "y", "spatial_ref"]')[["variable", "cells", "valid", "missing", "min", "max", "units"]])}

冰厚及速度变量的缺失掩膜与冰川掩膜一致：掩膜内7152格全有效，冰川掩膜外而矩形网格内的12858格缺失，不应理解为冰川内部缺测64.26%。一致性核验还发现：虽然v元数据称由vx/vy模长确定，当前30m数组的v比hypot(vx,vy)在全部7152格均略大；差值中位数{s["validation"]["netcdf_velocity_hypotenuse_residual_median"]:.5f}、均值{s["validation"]["netcdf_velocity_hypotenuse_residual_mean"]:.5f}、最大{s["validation"]["netcdf_velocity_hypotenuse_max_abs_error"]:.5f} m/年。速度模长与分量被分别双线性重采样可产生这种差异，这是结合元数据的推测，附件未明确确认处理顺序。本审计保留原变量并记录差异，不自行修改源数据。

![冰川网格](../output/data_audit/spatial/glacier_native_grid.png)

## 附件3长期高程变化与冰川边界

官方RAR内含《文档说明.docx》，正文提取副本为 `attachment3_document_text.txt`。其说明确认：围绕2026-08-26冰岩崩源区构建200km范围；RGI6/RGI7边界及Hugonnet等发布的2000—2020冰川高程变化产品。四个时期：2000—2005、2005—2010、2010—2015、2015—2020；每期有14片×3种产品，共168个TIFF。

{mdtable(pd.DataFrame([dict(source=v["source"], records=v["records"], CRS=v["crs"], invalid=v["invalid"]) for v in vectors if v["source"].startswith("attachment_3")]))}

dhdt为高程变化**率**，dhdt_err为误差，不能混作高程/冰厚或短期速度。上游作者目录已确认m/年与1σ，但本地派生栅格的单位/误差处理继承关系仍待核实，见[官方与上游复核](metadata-review.md)。UTM和GCS对应重复表达，不是两组独立样本。逐TIFF原始CRS、范围、分辨率、nodata、精确有效/缺失计数及数值范围见 `glacier_raster_inventory.csv`；分期和产品汇总见 `glacier_period_summary.csv`。RGI6 `BgnDate`/`EndDate`与RGI7 `src_date`仅记录实际存储值，业务含义及特殊日期/缺失编码待上游字典确认，不作事件日期；完整日期分布见 `glacier_inventory_date_counts.csv`。RGI6有1个无效几何，原因与ID见 `invalid_geometry_details.csv`，本审计保留原始几何未自动修复。RGI6/7数量不同不能直接解释为冰川新增/消失；版本、边界或拆分等影响需要另行核对。

## 附件5土地覆盖

2020—2023年每年3957×6336，EPSG:4326、uint8、nodata=0。四年CRS与网格需保持一致；像元大小以度表达，面积统计使用椭球面积。原始类别数值保持不变：附件内未发现类码释义；沿官网来源已找到上游作者字典，本地是否保持编码仍待核实，见[官方与上游复核](metadata-review.md)。

{mdtable(pd.DataFrame(s["landcover"])[["year", "valid_pixels", "missing_pixels", "missing_fraction", "valid_area_km2", "missing_area_km2"]])}

所有类码含nodata的精确频数及椭球面积见 `landcover_class_counts.csv`；相邻年有效像元的数字类码转移见 `landcover_transitions.csv`。转移仅表示编码变化，不能在缺少分类精度/制作说明时解释为真实土地利用变化，也不能推断因果。

四年CRS和形状完全一致；2022年仿射系数有浮点尾差，四角最大位置差{s["validation"]["landcover_max_corner_displacement_pixels"]:.4g}像元，小于预设1e-6像元容差，可直接对比，无需重采样。空间可用性另按历史属性坐标及附件4全部像元中心核验（最近邻类别查询；不对类别做双线性插值）：

{mdtable(pd.DataFrame(s["landcover_spatial_coverage"])[["year", "historical_attribute_xy_valid", "historical_records", "source_grid_valid", "source_grid_cells", "glacier_mask_cells_valid", "glacier_mask_cells"]])}

nodata可能来自县界裁切或产品掩膜，不能仅凭全矩形缺失率判断观测失败，更不能将0当作一种土地覆盖。

![土地覆盖类码](../output/data_audit/spatial/landcover_codes.png)

## 附件8人口：只支持县级口径

仅1个县级Polygon，{pop.crs}，几何无效={s["population"]["invalid"]}。`合计`={p["合计"]}，`男`+`女`={p["男"]}+{p["女"]}={p["男"] + p["女"]}，`城镇人`+`乡村人`={p["城镇人"]}+{p["乡村人"]}={p["城镇人"] + p["乡村人"]}。另有`人口数`={p["人口数"]}、`户数`={p["户数"]}、`户规模`={p["户规模"]}。人口数/户数={p["人口数"] / p["户数"]:.4f}只是算术关系，不能据此命名为户籍/家庭户人口。逐字段口径与差值{p["合计"] - p["人口数"]}的原因未明，不认作漏报或异常。

本附件没有村镇点位、建筑人口、人口栅格或县内分布，**不可直接外推局地栅格人口/源区暴露人口**。面积均摊是额外假设而不是观测，本审计不做此操作。

## 输出与使用限制

全部机器可读结果在 `output/data_audit/spatial/`：总索引 `spatial_summary.json`；档案清单 `archive_inventory.json`；字段字典 `vector_fields.csv`；矢量质量 `vector_audit.json`；DEM核验 `dem_audit.json`、`historical_dem_coverage.csv`、`dem_source_coverage.json`；NetCDF变量与原始元数据 `netcdf_variables.csv`、`netcdf_audit.json`；时间语义 `time_semantics.json`。三张图均提供PNG与SVG。所有计算来自本地附件，不联网下载底图，不把相关性当因果。

运行验证记录 `validation_checks.json`：像元有效+缺失计数守恒、每年类别频数总和、四年网格对齐、历史类型总数、速度v与hypot(vx,vy)差值、冰厚有效掩膜与glacier_mask一致性。程序对计数守恒与网格对齐设置断言；速度模长差异作为源数据质量发现保留，不当作程序失败。

后续可做覆盖范围内的解释性分层与机制假设；在获得明确事件发生时间、负样本构造依据和附加时空观测前，当前附件不支持宣称已建立可验证的逐日事件预报标签。DEM压缩包标题的2026-08-26不能自动证明它是灾前地形；XML的lineage/Process明确记录20260826、171843的Clip操作（见逐项证据与`dem_metadata_dates.json`）。处理日志和创建/同步日期均不等于观测获取时间；需补充获取与制作时序，避免时间泄漏。
"""
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
