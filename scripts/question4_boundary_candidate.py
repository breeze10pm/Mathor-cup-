"""Small, reproducible 1-D depth-averaged debris-flow scenario solver.

The model starts at the channel inlet after source-to-channel entry. It is not
a simulation of the hillslope avalanche, erosion, entrainment, or deposition.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from pyproj import Transformer

GRAVITY_M_S2 = 9.80665

def inlet_state(q_in, h_hint, h_inside, q_inside):
    """Q+h for supercritical entry; Q and outgoing invariant for subcritical.

    Subcritical discharge-only entry into a dry cell is underspecified and is
    rejected. A stopped prescribed pulse closes the upstream gate.
    """
    if q_in == 0: return h_inside, 0., 'wall'
    if q_in < 0: raise ValueError('Negative prescribed inlet is unsupported')
    if q_in / h_hint >= np.sqrt(GRAVITY_M_S2*h_hint): return h_hint,q_in,'supercritical'
    if h_inside <= 1e-12: raise ValueError('Subcritical entry needs a wet outgoing characteristic')
    ri=q_inside/h_inside-2*np.sqrt(GRAVITY_M_S2*h_inside)
    lo=(q_in*q_in/GRAVITY_M_S2)**(1/3)
    def residual(h): return q_in/h-2*np.sqrt(GRAVITY_M_S2*h)-ri
    if residual(lo)<0: raise ValueError('No subcritical characteristic boundary solution')
    hi=max(lo*2,h_inside*2)
    while residual(hi)>0: hi*=2
    for _ in range(64):
        mid=(lo+hi)/2
        if residual(mid)>0: lo=mid
        else: hi=mid
    return (lo+hi)/2,q_in,'subcritical'


def sample_raster_nearest(
    raster: np.ndarray,
    transform,
    x: np.ndarray,
    y: np.ndarray,
    point_crs: str,
    raster_crs: str,
    nodata_value: float | None,
    *,
    zero_is_nodata: bool = True,
) -> tuple[np.ndarray, dict[str, int]]:
    """Nearest-cell sample after CRS transformation; reject every invalid cell."""
    array = np.asarray(raster)
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if array.ndim != 2 or x_values.ndim != 1 or y_values.shape != x_values.shape:
        raise ValueError("raster must be 2D and x/y must be equal-length 1D arrays")
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise ValueError("sample coordinates contain non-finite values")
    transformer = Transformer.from_crs(point_crs, raster_crs, always_xy=True)
    raster_x, raster_y = transformer.transform(x_values, y_values)
    if abs(transform.b) > 1e-12 or abs(transform.d) > 1e-12:
        raise ValueError("rotated raster grids are not supported by nearest-cell sampler")
    cols_float = (np.asarray(raster_x) - transform.c) / transform.a
    rows_float = (np.asarray(raster_y) - transform.f) / transform.e
    # Affine inverse coordinates refer to pixel corners, not centers. For an
    # unrotated grid, floor selects the nearest pixel center (ties at edges).
    # rint shifts half of the samples and rejects valid last-pixel centers.
    cols = np.floor(cols_float).astype(int)
    rows = np.floor(rows_float).astype(int)
    inside = (rows >= 0) & (rows < array.shape[0]) & (cols >= 0) & (cols < array.shape[1])
    values = np.full(x_values.size, np.nan, dtype=float)
    values[inside] = array[rows[inside], cols[inside]].astype(float)
    nodata_mask = np.zeros(values.shape, dtype=bool)
    if nodata_value is not None:
        nodata_mask = np.isnan(values) if np.isnan(nodata_value) else values == nodata_value
    zero_mask = values == 0.0 if zero_is_nodata else np.zeros(values.shape, dtype=bool)
    invalid = (~inside) | (~np.isfinite(values)) | nodata_mask | zero_mask
    diagnostics = {
        "sample_count": int(values.size),
        "outside_count": int((~inside).sum()),
        "nodata_count": int(nodata_mask.sum()),
        "zero_count": int(zero_mask.sum()),
        "valid_count": int((~invalid).sum()),
    }
    if invalid.any():
        raise ValueError(f"DEM route sampling encountered invalid cells: {diagnostics}; no replacement was applied")
    return values, diagnostics


def prepare_uniform_profile(
    profile: Mapping[str, np.ndarray],
    start_chainage_m: float,
    end_chainage_m: float,
    dx_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate a finite centerline elevation profile onto cell centers."""
    chainage = np.asarray(profile["chainage_m"], dtype=float)
    elevation = np.asarray(profile["elev_m"], dtype=float)
    if chainage.ndim != 1 or elevation.ndim != 1 or chainage.size != elevation.size:
        raise ValueError("chainage_m and elev_m must be equal-length 1D arrays")
    if chainage.size < 2 or not np.isfinite(chainage).all() or not np.isfinite(elevation).all():
        raise ValueError("profile must contain at least two finite coordinate/elevation pairs")
    if np.any(np.diff(chainage) <= 0):
        raise ValueError("chainage_m must be strictly increasing")
    if not (np.isfinite(dx_m) and dx_m > 0 and end_chainage_m > start_chainage_m):
        raise ValueError("invalid domain or cell spacing")
    if start_chainage_m < chainage[0] or end_chainage_m > chainage[-1]:
        raise ValueError("requested route is not fully covered by the centerline profile")

    length = end_chainage_m - start_chainage_m
    n_cells = int(np.ceil(length / dx_m))
    actual_dx = length / n_cells
    centers = start_chainage_m + (np.arange(n_cells, dtype=float) + 0.5) * actual_dx
    bed = np.interp(centers, chainage, elevation)
    if not np.isfinite(bed).all():
        raise ValueError("interpolated bed contains non-finite elevations")
    return centers, bed


def _hll_flux(h_l: np.ndarray, q_l: np.ndarray, h_r: np.ndarray, q_r: np.ndarray):
    """HLL flux for the 1-D shallow-water conserved state [h, h*u]."""
    u_l = np.divide(q_l, h_l, out=np.zeros_like(q_l), where=h_l > 1e-12)
    u_r = np.divide(q_r, h_r, out=np.zeros_like(q_r), where=h_r > 1e-12)
    c_l = np.sqrt(GRAVITY_M_S2 * h_l)
    c_r = np.sqrt(GRAVITY_M_S2 * h_r)
    s_l = np.minimum(np.minimum(u_l - c_l, u_r - c_r), 0.0)
    s_r = np.maximum(np.maximum(u_l + c_l, u_r + c_r), 0.0)
    f_l_h = q_l
    f_r_h = q_r
    f_l_q = q_l * u_l + 0.5 * GRAVITY_M_S2 * h_l**2
    f_r_q = q_r * u_r + 0.5 * GRAVITY_M_S2 * h_r**2
    gap = s_r - s_l
    safe_gap = np.where(gap > 1e-12, gap, 1.0)
    h_flux = np.where(
        s_l >= 0,
        f_l_h,
        np.where(s_r <= 0, f_r_h, (s_r * f_l_h - s_l * f_r_h + s_l * s_r * (h_r - h_l)) / safe_gap),
    )
    q_flux = np.where(
        s_l >= 0,
        f_l_q,
        np.where(s_r <= 0, f_r_q, (s_r * f_l_q - s_l * f_r_q + s_l * s_r * (q_r - q_l)) / safe_gap),
    )
    return h_flux, q_flux, s_l, s_r


def _interface_fluxes(
    h: np.ndarray,
    q: np.ndarray,
    bed: np.ndarray,
    inlet_depth_m: float,
    inlet_unit_discharge_m2_s: float,
):
    """Hydrostatic reconstruction and HLL fluxes with side-specific bed terms."""
    n = h.size
    h_l = np.empty(n + 1)
    q_l = np.empty(n + 1)
    z_l = np.empty(n + 1)
    h_r = np.empty(n + 1)
    q_r = np.empty(n + 1)
    z_r = np.empty(n + 1)

    h_l[0], q_l[0], z_l[0] = inlet_depth_m, inlet_unit_discharge_m2_s, bed[0]
    h_r[0], q_r[0], z_r[0] = h[0], q[0], bed[0]
    h_l[1:n], q_l[1:n], z_l[1:n] = h[:-1], q[:-1], bed[:-1]
    h_r[1:n], q_r[1:n], z_r[1:n] = h[1:], q[1:], bed[1:]
    h_l[n], q_l[n], z_l[n] = h[-1], q[-1], bed[-1]
    h_r[n], q_r[n], z_r[n] = h[-1], q[-1], bed[-1]

    z_star = np.maximum(z_l, z_r)
    h_l_star = np.maximum(0.0, h_l + z_l - z_star)
    h_r_star = np.maximum(0.0, h_r + z_r - z_star)
    u_l = np.divide(q_l, h_l, out=np.zeros_like(q_l), where=h_l > 1e-12)
    u_r = np.divide(q_r, h_r, out=np.zeros_like(q_r), where=h_r > 1e-12)
    q_l_star = h_l_star * u_l
    q_r_star = h_r_star * u_r
    f_h, f_q, s_l, s_r = _hll_flux(h_l_star, q_l_star, h_r_star, q_r_star)

    # Hydrostatic reconstruction side corrections make a lake-at-rest state
    # well-balanced over piecewise bed elevations.
    corr_l = 0.5 * GRAVITY_M_S2 * (h_l**2 - h_l_star**2)
    corr_r = 0.5 * GRAVITY_M_S2 * (h_r**2 - h_r_star**2)
    q_flux_for_left = f_q + corr_l
    q_flux_for_right = f_q + corr_r
    # The specified hydrograph is a volumetric boundary condition; preserve its
    # exact unit discharge instead of allowing a Riemann boundary to alter mass.
    hb,qb,regime=inlet_state(inlet_unit_discharge_m2_s,inlet_depth_m,h[0],q[0])
    if regime=='wall':
        _,wall_momentum,_,_=_hll_flux(np.array([h[0]]),np.array([-q[0]]),np.array([h[0]]),np.array([q[0]]))
        f_h[0]=0.; q_flux_for_left[0]=q_flux_for_right[0]=wall_momentum[0]
    else:
        f_h[0]=qb
        q_flux_for_left[0]=q_flux_for_right[0]=qb*qb/hb+.5*GRAVITY_M_S2*hb*hb
    return f_h, q_flux_for_left, q_flux_for_right, s_l, s_r


def run_simulation(
    *,
    x_m: np.ndarray,
    bed_m: np.ndarray,
    width_m: float,
    volume_m3: float,
    pulse_duration_s: float,
    inlet_depth_m: float,
    initial_depth_profile_m: np.ndarray | None = None,
    mu: float,
    xi_m_s2: float,
    end_time_s: float,
    cfl: float = 0.4,
    output_interval_s: float = 1.0,
) -> dict[str, object]:
    """Run an initially dry channel with a rectangular volume hydrograph.

    State: h (m), q=h*u (m2/s). Discharge Q is width*unit discharge (m3/s).
    The mass equation is conservative finite volume. Momentum uses HLL fluxes,
    hydrostatic reconstruction, and a split semi-implicit Voellmy source.
    """
    x = np.asarray(x_m, dtype=float)
    z = np.asarray(bed_m, dtype=float)
    if x.ndim != 1 or z.ndim != 1 or x.size != z.size or x.size < 3:
        raise ValueError("x_m and bed_m must be equal-length 1D arrays with at least 3 cells")
    spacing = np.diff(x)
    if not np.isfinite(x).all() or not np.isfinite(z).all() or not np.allclose(spacing, spacing[0], rtol=1e-8, atol=1e-8):
        raise ValueError("solver grid and bed must be finite and uniformly spaced")
    dx = float(spacing[0])
    if dx <= 0:
        raise ValueError("x_m must increase downstream")
    if width_m <= 0 or volume_m3 < 0 or pulse_duration_s <= 0 or inlet_depth_m <= 0:
        raise ValueError("width, pulse duration, and inlet depth must be positive; volume cannot be negative")
    if mu < 0 or xi_m_s2 <= 0 or end_time_s <= 0 or not 0 < cfl <= 0.5:
        raise ValueError("invalid friction, horizon, or CFL value")
    if output_interval_s <= 0:
        raise ValueError("output_interval_s must be positive")

    n = x.size
    if initial_depth_profile_m is None:
        h = np.zeros(n, dtype=float)
    else:
        h = np.asarray(initial_depth_profile_m, dtype=float).copy()
        if h.shape != (n,) or not np.isfinite(h).all() or np.any(h < 0):
            raise ValueError("initial_depth_profile_m must be finite, nonnegative, and match the grid")
    q = np.zeros(n, dtype=float)
    initial_storage = float(width_m * dx * h.sum())
    slope = -np.gradient(z, dx)
    theta_cos = 1.0 / np.sqrt(1.0 + slope**2)
    h_in = float(inlet_depth_m)
    volume_rate = volume_m3 / pulse_duration_s
    next_output = output_interval_s
    t = 0.0
    cumulative_in = 0.0
    cumulative_out = 0.0
    snapshots: list[dict[str, object]] = []
    balance_rows: list[dict[str, float]] = []
    min_dt = np.inf
    max_cfl = 0.0
    step_count = 0

    def store_snapshot() -> None:
        wet = np.flatnonzero(h > 1e-3)
        front_i = int(wet[-1]) if wet.size else 0
        u = np.divide(q, h, out=np.zeros_like(q), where=h > 1e-12)
        front_speed = max(0.0, float(u[front_i])) if wet.size else 0.0
        snapshots.append(
            {
                "time_s": float(t),
                "depth_m": h.copy(),
                "velocity_m_s": u.copy(),
                "discharge_m3_s": (width_m * q).copy(),
                "front_position_m": float(x[front_i]) if wet.size else float(x[0] - 0.5 * dx),
                "front_speed_m_s": front_speed,
                "front_depth_m": float(h[front_i]) if wet.size else 0.0,
                "front_discharge_m3_s": float(width_m * q[front_i]) if wet.size else 0.0,
                "mass_m3": float(width_m * dx * h.sum()),
            }
        )

    store_snapshot()
    while t < end_time_s - 1e-10:
        q_in = volume_rate / width_m if t < pulse_duration_s - 1e-10 else 0.0
        u = np.divide(q, h, out=np.zeros_like(q), where=h > 1e-12)
        hb,qb,_=inlet_state(q_in,h_in,h[0],q[0])
        boundary_speed = abs(qb / hb) + np.sqrt(GRAVITY_M_S2 * hb) if q_in > 0 else 0.0
        wave_speed = max(float(np.max(np.abs(u) + np.sqrt(GRAVITY_M_S2 * h))), float(boundary_speed))
        dt_cfl = cfl * dx / max(float(wave_speed), 1e-6)
        dt = min(dt_cfl, end_time_s - t, next_output - t if next_output > t + 1e-10 else np.inf)
        if t < pulse_duration_s - 1e-10:
            dt = min(dt, pulse_duration_s - t)
        if not np.isfinite(dt) or dt <= 1e-12:
            raise RuntimeError("time step collapsed; check profile and CFL conditions")
        boundary_depth = h_in if q_in > 0 else float(h[0])
        h_flux, q_flux_left, q_flux_right, s_l, s_r = _interface_fluxes(h, q, z, boundary_depth, q_in)
        h_new = h - (dt / dx) * (h_flux[1:] - h_flux[:-1])
        q_new = q - (dt / dx) * (q_flux_left[1:] - q_flux_right[:-1])

        # Inlet mass flux is imposed exactly and downstream outlet is open.
        # Voellmy source: Coulomb resistance plus velocity-squared resistance.
        active = h_new > 1e-12
        u_new = np.divide(q_new, h_new, out=np.zeros_like(q_new), where=active)
        coulomb_drop = dt * mu * GRAVITY_M_S2 * theta_cos
        u_new = np.sign(u_new) * np.maximum(np.abs(u_new) - coulomb_drop, 0.0)
        turbulent_factor = dt * GRAVITY_M_S2 * theta_cos / (xi_m_s2 * np.maximum(h_new, 1e-9))
        u_new = np.divide(u_new, 1.0 + turbulent_factor * np.abs(u_new))
        q_new = np.where(active, h_new * u_new, 0.0)

        if float(h_new.min()) < -1e-10:
            raise FloatingPointError(f"negative depth {float(h_new.min()):.3g} m; CFL update is not positivity preserving")
        h_new[h_new < 0.0] = 0.0
        if not np.isfinite(h_new).all() or not np.isfinite(q_new).all():
            raise FloatingPointError("non-finite solver state")

        mass_in_step = width_m * q_in * dt
        outlet_q = float(h_flux[-1])  # Signed open-boundary exchange, including possible backflow.
        mass_out_step = width_m * outlet_q * dt
        cumulative_in += mass_in_step
        cumulative_out += mass_out_step
        h, q = h_new, q_new
        t_next = t + dt
        courant = dt * max(float(wave_speed), 1e-6) / dx
        max_cfl = max(max_cfl, courant)
        min_dt = min(min_dt, dt)
        t = min(t_next, end_time_s)
        step_count += 1
        mass = float(width_m * dx * h.sum())
        residual = mass - (initial_storage + cumulative_in - cumulative_out)
        denom = max(initial_storage + cumulative_in, 1.0)
        balance_rows.append(
            {
                "time_s": t,
                "mass_m3": mass,
                "injected_m3": cumulative_in,
                "outlet_m3": cumulative_out,
                "residual_m3": residual,
                "relative_error": abs(residual) / denom,
                "cfl_number": courant,
                "dt_s": dt,
            }
        )
        if t >= next_output - 1e-9 or t >= end_time_s - 1e-9:
            store_snapshot()
            next_output += output_interval_s

    times = np.asarray([s["time_s"] for s in snapshots], dtype=float)
    front = np.asarray([s["front_position_m"] for s in snapshots], dtype=float)
    max_front = float(np.max(front))
    relative_error = balance_rows[-1]["relative_error"] if balance_rows else 0.0
    return {
        "times_s": times,
        "depth_m": np.stack([s["depth_m"] for s in snapshots]),
        "velocity_m_s": np.stack([s["velocity_m_s"] for s in snapshots]),
        "discharge_m3_s": np.stack([s["discharge_m3_s"] for s in snapshots]),
        "front_position_m": front,
        "front_speed_m_s": np.asarray([s["front_speed_m_s"] for s in snapshots]),
        "front_depth_m": np.asarray([s["front_depth_m"] for s in snapshots]),
        "front_discharge_m3_s": np.asarray([s["front_discharge_m3_s"] for s in snapshots]),
        "mass_m3": np.asarray([s["mass_m3"] for s in snapshots]),
        "mass_balance": np.asarray(
            [[r[k] for k in ("time_s", "mass_m3", "injected_m3", "outlet_m3", "residual_m3", "relative_error", "cfl_number", "dt_s")] for r in balance_rows],
            dtype=float,
        ),
        "mass_balance_columns": ("time_s", "mass_m3", "injected_m3", "outlet_m3", "residual_m3", "relative_error", "cfl_number", "dt_s"),
        "injected_volume_m3": float(cumulative_in),
        "initial_storage_volume_m3": float(initial_storage),
        "outlet_volume_m3": float(cumulative_out),
        "final_mass_m3": float(width_m * dx * h.sum()),
        "relative_mass_error": float(relative_error),
        "max_cfl_number": float(max_cfl),
        "minimum_time_step_s": float(min_dt if np.isfinite(min_dt) else 0.0),
        "step_count": int(step_count),
        "max_front_position_m": max_front,
        "cell_center_m": x.copy(),
        "bed_m": z.copy(),
        "cell_width_m": dx,
        "channel_width_m": float(width_m),
    }
