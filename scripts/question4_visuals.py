"""Pillow-based scientific plots, avoiding GUI/font-backend dependencies."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, box


def _font(size: int = 14):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow versions before scalable default fonts.
        return ImageFont.load_default()


def _limits(series, axis: int, explicit=None):
    if explicit is not None:
        return tuple(map(float, explicit))
    else:
        values = [np.asarray(item[axis], dtype=float) for item in series]
        valid = np.concatenate([v[np.isfinite(v)] for v in values if np.isfinite(v).any()]) if values else np.asarray([0.0, 1.0])
        lo, hi = float(valid.min()), float(valid.max())
    if not math.isfinite(lo) or not math.isfinite(hi):
        return 0.0, 1.0
    if abs(hi - lo) < 1e-12:
        pad = max(abs(lo) * 0.05, 1.0)
        return lo - pad, hi + pad
    pad = 0.06 * (hi - lo)
    return lo - pad, hi + pad


def draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: list[tuple[str, Iterable[float], Iterable[float], str]],
    xlim=None,
    ylim=None,
    fill_bed: tuple[Iterable[float], Iterable[float], Iterable[float], str] | None = None,
) -> None:
    left, top, right, bottom = box
    title_font, label_font, small_font = _font(16), _font(12), _font(10)
    draw.rectangle(box, fill="white", outline="#cbd5e1", width=1)
    draw.text((left + 12, top + 8), title, fill="#0f172a", font=title_font)
    px0, py0, px1, py1 = left + 74, top + 40, right - 18, bottom - 54
    if px1 <= px0 or py1 <= py0:
        return
    xmin, xmax = _limits([(name, np.asarray(x, dtype=float), np.asarray(y, dtype=float), color) for name, x, y, color in series], 1, xlim)
    ymin, ymax = _limits([(name, np.asarray(x, dtype=float), np.asarray(y, dtype=float), color) for name, x, y, color in series], 2, ylim)

    def sx(value):
        return px0 + (float(value) - xmin) / (xmax - xmin) * (px1 - px0)

    def sy(value):
        return py1 - (float(value) - ymin) / (ymax - ymin) * (py1 - py0)

    for tick in range(5):
        frac = tick / 4
        xv = xmin + frac * (xmax - xmin)
        yv = ymin + frac * (ymax - ymin)
        xpixel = int(px0 + frac * (px1 - px0))
        ypixel = int(py1 - frac * (py1 - py0))
        draw.line((xpixel, py0, xpixel, py1), fill="#e2e8f0", width=1)
        draw.line((px0, ypixel, px1, ypixel), fill="#e2e8f0", width=1)
        draw.text((xpixel - 20, py1 + 6), f"{xv:.2g}", fill="#334155", font=small_font)
        draw.text((left + 4, ypixel - 5), f"{yv:.2g}", fill="#334155", font=small_font)
    draw.rectangle((px0, py0, px1, py1), outline="#334155", width=1)
    draw.text(((px0 + px1) // 2 - 35, bottom - 28), x_label, fill="#0f172a", font=label_font)
    draw.text((left + 5, top + 26), y_label, fill="#0f172a", font=small_font)

    if fill_bed is not None:
        x, bed, surface, color = fill_bed
        x = np.asarray(x, dtype=float)
        bed = np.asarray(bed, dtype=float)
        surface = np.asarray(surface, dtype=float)
        upper = [(sx(xx), sy(yy)) for xx, yy in zip(x, surface)]
        lower = [(sx(xx), sy(yy)) for xx, yy in zip(x[::-1], bed[::-1])]
        if len(upper) > 1:
            draw.polygon(upper + lower, fill=color)
            draw.line(upper, fill="#0284c7", width=2)
            draw.line([(sx(xx), sy(yy)) for xx, yy in zip(x, bed)], fill="#475569", width=1)

    legend_x, legend_y = px0 + 8, py0 + 7
    for name, x, y, color in series:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        points = [(sx(xx), sy(yy)) for xx, yy in zip(x[valid], y[valid])]
        if len(points) > 1:
            draw.line(points, fill=color, width=2)
        elif points:
            cx, cy = points[0]
            draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=color)
        draw.line((legend_x, legend_y + 5, legend_x + 18, legend_y + 5), fill=color, width=2)
        draw.text((legend_x + 22, legend_y), name, fill="#0f172a", font=small_font)
        legend_y += 14


def save_line_chart(path, *, title, x_label, y_label, series, xlim=None, ylim=None, size=(1400, 800)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw_panel(draw, (0, 0, size[0] - 1, size[1] - 1), title=title, x_label=x_label, y_label=y_label, series=series, xlim=xlim, ylim=ylim)
    image.save(path, format="PNG")


def save_bar_chart(path, *, title, categories, values, y_label, size=(1800, 800)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 12), title, fill="#0f172a", font=_font(18))
    left, top, right, bottom = 80, 55, size[0] - 25, size[1] - 115
    vals = np.asarray(values, dtype=float)
    ymax = max(float(np.max(vals)) * 1.12, 1.0)
    for tick in range(5):
        frac = tick / 4
        y = bottom - frac * (bottom - top)
        draw.line((left, int(y), right, int(y)), fill="#e2e8f0", width=1)
        draw.text((8, int(y) - 5), f"{frac*ymax:.2g}", fill="#334155", font=_font(11))
    draw.rectangle((left, top, right, bottom), outline="#334155", width=1)
    draw.text((8, 38), y_label, fill="#0f172a", font=_font(12))
    count = len(categories)
    slot = (right - left) / max(count, 1)
    for i, (label, value) in enumerate(zip(categories, vals)):
        x0 = left + i * slot + slot * 0.2
        x1 = left + (i + 1) * slot - slot * 0.2
        y1 = bottom - (float(value) / ymax) * (bottom - top)
        draw.rectangle((int(x0), int(y1), int(x1), bottom), fill="#0ea5e9")
        draw.text((int(x0), bottom + 8), str(label), fill="#0f172a", font=_font(11))
        draw.text((int(x0), int(y1) - 16), f"{value:.2g}", fill="#0f172a", font=_font(10))
    image.save(path, format="PNG")


def save_multi_panel(path, panels, *, cols=2, size=(1800, 1200)):
    rows = int(math.ceil(len(panels) / cols))
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    w, h = size[0] // cols, size[1] // rows
    for i, panel in enumerate(panels):
        row, col = divmod(i, cols)
        draw_panel(
            draw,
            (col * w, row * h, min((col + 1) * w - 1, size[0] - 1), min((row + 1) * h - 1, size[1] - 1)),
            title=panel["title"], x_label=panel["x_label"], y_label=panel["y_label"],
            series=panel.get("series", []), xlim=panel.get("xlim"), ylim=panel.get("ylim"), fill_bed=panel.get("fill_bed"),
        )
    image.save(path, format="PNG")


def _line_parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [list(geom.coords)]
    if isinstance(geom, MultiLineString):
        return [list(g.coords) for g in geom.geoms]
    if isinstance(geom, Polygon):
        return [list(geom.exterior.coords), *[list(r.coords) for r in geom.interiors]]
    if isinstance(geom, MultiPolygon):
        return [coords for g in geom.geoms for coords in _line_parts(g)]
    if isinstance(geom, GeometryCollection):
        return [coords for g in geom.geoms for coords in _line_parts(g)]
    return []


def save_map(path, *, extent_geometries, route_geometries, simulated_geometries, points, title):
    size = (1400, 1250)
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    title_font, font = _font(20), _font(13)
    draw.text((25, 20), title, fill="#0f172a", font=title_font)
    all_coords = []
    for geom in list(route_geometries) + list(simulated_geometries.values()):
        for part in _line_parts(geom):
            all_coords.extend(part)
    all_coords.extend(points.values())
    xs = [xy[0] for xy in all_coords]
    ys = [xy[1] for xy in all_coords]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    pad_x, pad_y = max((xmax - xmin) * 0.04, 100), max((ymax - ymin) * 0.04, 100)
    xmin, xmax, ymin, ymax = xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y
    map_box = (70, 65, 1320, 1130)
    view = box(xmin, ymin, xmax, ymax)

    def project(xy):
        x, y = xy[:2]
        px = map_box[0] + (x - xmin) / (xmax - xmin) * (map_box[2] - map_box[0])
        py = map_box[3] - (y - ymin) / (ymax - ymin) * (map_box[3] - map_box[1])
        return int(px), int(py)

    for n, source_geom in enumerate(extent_geometries):
        geom = source_geom.intersection(view)
        color, width = ("#64748b", 1) if n == 0 else ("#a855f7", 1)
        for part in _line_parts(geom):
            if len(part) > 1:
                draw.line([project(xy) for xy in part], fill=color, width=width)
    for geom in route_geometries:
        for part in _line_parts(geom):
            if len(part) > 1:
                draw.line([project(xy) for xy in part], fill="#cbd5e1", width=2)
    palette = {"A_reference": "#dc2626", "A_low_resistance": "#2563eb", "A_high_resistance": "#d97706", "B_reference": "#16a34a"}
    for sid, geom in simulated_geometries.items():
        for part in _line_parts(geom):
            if len(part) > 1:
                draw.line([project(xy) for xy in part], fill=palette.get(sid, "#0f766e"), width=4)
    for name, xy in points.items():
        px, py = project(xy)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#111827", outline="white", width=2)
        draw.text((px + 8, py - 8), name, fill="#0f172a", font=font)
    draw.text((75, 1150), "EPSG:32645 · modeled reach is 1D centerline only · extents are post-event interpretation", fill="#334155", font=font)
    image.save(path, format="PNG")


def save_animation_gif(path, *, state, route, extent_geometries, x_utm, y_utm, interval_s=20.0):
    times = np.asarray(state["times_s"], dtype=float)
    step = max(1, int(round(interval_s / max(float(np.median(np.diff(times))), 1e-9))))
    indices = list(range(0, len(times), step))
    if indices[-1] != len(times) - 1:
        indices.append(len(times) - 1)
    route_xy = list(route.coords)
    bounds_coords = route_xy[:]
    for geom in extent_geometries:
        for part in _line_parts(geom):
            bounds_coords.extend(part)
    xs, ys = zip(*[(c[0], c[1]) for c in bounds_coords])
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    pad_x, pad_y = max((xmax - xmin) * 0.04, 100), max((ymax - ymin) * 0.04, 100)
    xmin, xmax, ymin, ymax = xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y
    width, height = 1100, 500
    mapbox = (30, 55, 490, 455)
    chartbox = (520, 45, 1080, 465)

    def project(xy):
        x, y = xy[:2]
        return int(mapbox[0] + (x - xmin) / (xmax - xmin) * (mapbox[2] - mapbox[0])), int(mapbox[3] - (y - ymin) / (ymax - ymin) * (mapbox[3] - mapbox[1]))

    frames = []
    for i in indices:
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((25, 15), f"Computed A-reference state, relative t={times[i]:.0f} s", fill="#0f172a", font=_font(18))
        for n, geom in enumerate(extent_geometries):
            color = "#94a3b8" if n == 0 else "#a855f7"
            for part in _line_parts(geom):
                if len(part) > 1:
                    draw.line([project(xy) for xy in part], fill=color, width=1)
        draw.line([project(xy) for xy in route_xy], fill="#64748b", width=2)
        dist = float(np.clip(state["front_position_m"][i], 0.0, float(state["cell_center_m"][-1] + state["cell_width_m"] / 2)))
        # `route` is the full A chain; map front chainage is obtained by linear
        # interpolation along the centerline geometry in the builder-provided arrays.
        idx = int(np.argmin(np.abs(np.asarray(state["cell_center_m"]) - dist)))
        point_xy = (float(x_utm[idx]), float(y_utm[idx]))
        px, py = project(point_xy)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill="#dc2626", outline="white", width=2)
        draw_panel(
            draw, chartbox, title="Longitudinal flow state", x_label="Distance from inlet (km)", y_label="Elevation (m)",
            series=[],
            xlim=(float(state["cell_center_m"][0] / 1000), float(state["cell_center_m"][-1] / 1000)),
            ylim=(float(np.min(state["bed_m"]) - 10), float(np.max(state["bed_m"]) + max(np.max(state["depth_m"][i]), 10))),
            fill_bed=(np.asarray(state["cell_center_m"]) / 1000, state["bed_m"], state["bed_m"] + state["depth_m"][i], "#bae6fd"),
        )
        frames.append(image.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=200, loop=0, optimize=True)
