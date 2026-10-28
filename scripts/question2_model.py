"""Evidence-aware mechanics and condition-index helpers for Question 2.

The returned indices are transparent scenario scores, never probabilities.
Missing physical conditions remain missing rather than being imputed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def slope_membership(
    slope_deg: float, threshold_low_deg: float, threshold_high_deg: float
) -> float:
    """Linear exploratory slope-condition membership on [0, 1]."""
    if not _finite(slope_deg):
        return math.nan
    if threshold_high_deg <= threshold_low_deg:
        raise ValueError("threshold_high_deg must exceed threshold_low_deg")
    return min(1.0, max(0.0, (float(slope_deg) - threshold_low_deg) / (threshold_high_deg - threshold_low_deg)))


def distance_connectivity(distance_m: float, decay_length_m: float) -> float:
    """Exponential proximity score exp(-d / L), with explicit scale L in metres."""
    if not _finite(distance_m):
        return math.nan
    if distance_m < 0 or decay_length_m <= 0:
        raise ValueError("distance_m must be nonnegative and decay_length_m positive")
    return math.exp(-float(distance_m) / float(decay_length_m))


def scenario_index(
    components: Mapping[str, float | None], weights: Mapping[str, float] | None = None
) -> float | None:
    """Weighted component mean; any required unknown component yields None."""
    if not components or any(not _finite(value) for value in components.values()):
        return None
    if weights is None:
        weights = {name: 1.0 for name in components}
    if set(weights) != set(components):
        raise ValueError("weights and component names must match")
    if any(not math.isfinite(float(weight)) or weight < 0 for weight in weights.values()):
        raise ValueError("weights must be finite and nonnegative")
    weight_sum = sum(float(weight) for weight in weights.values())
    if weight_sum <= 0:
        raise ValueError("at least one weight must be positive")
    if any(not 0 <= float(value) <= 1 for value in components.values()):
        raise ValueError("condition components must be within [0, 1]")
    return sum(float(components[name]) * float(weights[name]) for name in components) / weight_sum


def cascade_state(*, source: bool, channel: bool, water: bool | None) -> str:
    """Return a causal-gate state; unknown water is never coerced to a boolean."""
    if not source:
        return "source_gate_not_met"
    if not channel:
        return "channel_gate_not_met"
    if water is None:
        return "indeterminate_water_unobserved"
    if not water:
        return "water_gate_not_met"
    return "conditional_gates_met"


def infinite_slope_factor_of_safety(
    slope_deg: float,
    cohesion_kpa: float,
    friction_angle_deg: float,
    unit_weight_kn_m3: float,
    soil_depth_m: float,
    saturation_ratio: float,
    water_unit_weight_kn_m3: float = 9.81,
) -> float:
    """USGS infinite-slope FS for a shallow soil layer, not intact rock/ice.

    FS = c'/(gamma*z*sin(alpha)) + tan(phi')/tan(alpha)
         - m*gamma_w*tan(phi')/(gamma*tan(alpha)).
    FS <= 1 is limit-equilibrium/unstable in the idealized model.
    """
    values = (slope_deg, cohesion_kpa, friction_angle_deg, unit_weight_kn_m3,
              soil_depth_m, saturation_ratio, water_unit_weight_kn_m3)
    if not all(_finite(value) for value in values):
        return math.nan
    alpha = math.radians(float(slope_deg))
    phi = math.radians(float(friction_angle_deg))
    if not (0 < slope_deg < 90 and 0 <= friction_angle_deg < 90):
        raise ValueError("slope and friction angles must be in physical ranges")
    if cohesion_kpa < 0 or unit_weight_kn_m3 <= 0 or soil_depth_m <= 0 or water_unit_weight_kn_m3 <= 0:
        raise ValueError("strength, unit weight, and soil depth are invalid")
    if not 0 <= saturation_ratio <= 1:
        raise ValueError("saturation_ratio must be within [0, 1]")
    return (
        cohesion_kpa / (unit_weight_kn_m3 * soil_depth_m * math.sin(alpha))
        + math.tan(phi) / math.tan(alpha)
        - saturation_ratio * water_unit_weight_kn_m3 * math.tan(phi)
        / (unit_weight_kn_m3 * math.tan(alpha))
    )


def bed_wetness_gate(water_content_m3_m3: float | None, threshold_m3_m3: float) -> bool | None:
    """Experimental wet-bed threshold comparator; None means unobserved locally."""
    if water_content_m3_m3 is None or not _finite(water_content_m3_m3):
        return None
    if not 0 <= water_content_m3_m3 <= 1 or not 0 <= threshold_m3_m3 <= 1:
        raise ValueError("volumetric water contents must be within [0, 1]")
    return float(water_content_m3_m3) >= threshold_m3_m3
