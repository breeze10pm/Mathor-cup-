"""Pure, evidence-aware time and arrival helpers for Question 3.

No function in this module estimates a trigger probability. Arrival speeds are
explicitly retrospective when they use the reported port-arrival anchor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_aware_datetime(value: str | datetime | None) -> datetime | None:
    """Parse an ISO datetime and reject missing timezone information."""
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timezone required: {value}")
    return parsed


def validate_event_chronology(
    onset: datetime, transition_start: datetime, transition_end: datetime, arrival: datetime
) -> None:
    """Check event stage order by instant, allowing different timezone offsets."""
    times = [onset, transition_start, transition_end, arrival]
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        raise ValueError("All event times must include a timezone")
    if not (onset <= transition_start <= transition_end <= arrival):
        raise ValueError("Reported onset, transition phase and arrival are not chronologically ordered")


def build_trigger_intervals(
    onset: datetime, transition_start: datetime, transition_end: datetime, arrival: datetime
) -> list[dict[str, Any]]:
    """Build evidence bounds without converting process times to probabilities."""
    validate_event_chronology(onset, transition_start, transition_end, arrival)
    return [
        {
            "interval_id": "conditional_event_chain_bound",
            "target_stage": "physical_debris_flow_trigger",
            "lower_time": onset.isoformat(),
            "upper_time": arrival.isoformat(),
            "is_statistical": False,
            "is_trigger_time_interval": True,
            "status": "conditional_evidence_bound",
            "interpretation": "Under the reported single-chain assumption, trigger is no earlier than reported ice-collapse onset and no later than port arrival; endpoint timing uncertainty is not quantified.",
        },
        {
            "interval_id": "reported_transition_phase",
            "target_stage": "debris_to_mudflow_transition_phase",
            "lower_time": transition_start.isoformat(),
            "upper_time": transition_end.isoformat(),
            "is_statistical": False,
            "is_trigger_time_interval": False,
            "status": "user_reported_process_phase_not_physical_trigger",
            "interpretation": "Reported 51-second transition phase; it is not presumed to be the exact physical trigger time.",
        },
        {
            "interval_id": "nominal_95_prediction_interval",
            "target_stage": "physical_debris_flow_trigger",
            "lower_time": None,
            "upper_time": None,
            "is_statistical": False,
            "is_trigger_time_interval": False,
            "status": "not_estimable",
            "interpretation": "No justified event-time error distribution or independent labeled events are available; no nominal 95% interval is fabricated.",
        },
    ]


def forecast_timing(
    initialization_time: datetime,
    event_time: datetime,
    publication_time: datetime | None = None,
) -> dict[str, Any]:
    """Separate model initialization lag from actual issue/publication lead."""
    if initialization_time.tzinfo is None or event_time.tzinfo is None:
        raise ValueError("Initialization and event times must be timezone-aware")
    if publication_time is not None and publication_time.tzinfo is None:
        raise ValueError("Publication time must be timezone-aware when supplied")
    init_lag_h = (event_time - initialization_time).total_seconds() / 3600
    issue_lead_h = (
        (event_time - publication_time).total_seconds() / 3600
        if publication_time is not None else None
    )
    return {
        "initialization_to_event_hours": init_lag_h,
        "publication_time": publication_time.isoformat() if publication_time else None,
        "operational_lead_hours": issue_lead_h,
        "operational_lead_status": "computable_from_publication_time" if publication_time else "not_estimable_publication_time_unknown",
    }


def elapsed_tolerance_range_seconds(start: datetime, end: datetime, endpoint_tolerance_s: float) -> tuple[float, float]:
    """Bound elapsed time under symmetric endpoint tolerances; not a probability interval."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Interval endpoints must be timezone-aware")
    if endpoint_tolerance_s < 0 or end < start:
        raise ValueError("Tolerance must be nonnegative and interval chronologically ordered")
    elapsed = (end - start).total_seconds()
    return max(0.0, elapsed - 2 * endpoint_tolerance_s), elapsed + 2 * endpoint_tolerance_s


def arrival_scenarios(
    routes: list[dict[str, Any]],
    detection_time: datetime,
    reported_arrival: datetime,
    speed_factors: dict[str, float],
) -> list[dict[str, Any]]:
    """Compute event-anchored route arrival scenarios; never label as validation."""
    if detection_time.tzinfo is None or reported_arrival.tzinfo is None:
        raise ValueError("Detection and arrival times must be timezone-aware")
    anchor_elapsed_s = (reported_arrival - detection_time).total_seconds()
    if anchor_elapsed_s <= 0:
        raise ValueError("Reported arrival must follow the assumed detection time")
    if not routes or not speed_factors:
        raise ValueError("At least one route and one speed scenario are required")
    if any(float(factor) <= 0 for factor in speed_factors.values()):
        raise ValueError("Speed factors must be positive")

    rows: list[dict[str, Any]] = []
    for route in routes:
        distance_km = float(route["centerline_distance_km"])
        if distance_km <= 0:
            raise ValueError("Route distance must be positive")
        distance_m = distance_km * 1000
        anchor_speed = distance_m / anchor_elapsed_s
        for scenario, factor_raw in speed_factors.items():
            factor = float(factor_raw)
            speed = anchor_speed * factor
            travel_s = distance_m / speed
            predicted_arrival = detection_time + (reported_arrival - detection_time) / factor
            rows.append(
                {
                    "route_id": route["route_id"],
                    "scenario": scenario,
                    "speed_factor": factor,
                    "centerline_distance_km": distance_km,
                    "apparent_speed_m_s": speed,
                    "travel_time_seconds": travel_s,
                    "predicted_arrival_time": predicted_arrival.isoformat(),
                    "conditional_detection_to_arrival_lead_seconds": travel_s,
                    "arrival_error_vs_reported_seconds": (predicted_arrival - reported_arrival).total_seconds(),
                    "uses_reported_arrival_anchor": True,
                    "arrival_matches_anchor_by_construction": factor == 1.0,
                    "independent_validation": False,
                    "interval_is_statistical": False,
                    "interpretation": "Retrospective one-dimensional scenario; baseline speed is derived from reported onset-to-arrival and cannot independently verify that arrival.",
                }
            )
    return rows
