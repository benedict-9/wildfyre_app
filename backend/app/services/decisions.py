"""Pure proximity candidates and explicit operator timing scenarios."""
from datetime import datetime
import math

from app.risk import calculate_priority, calculate_response_window
from app.schemas import (
    DataMode, FireEvent, RiskResponse, ScenarioResponse, TimingScenario,
    WildlifeOccurrence, ZoneAssessment,
)

EARTH_RADIUS_KM = 6371.0088
CANDIDATE_RADIUS_KM = 25.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between validated coordinates, including the dateline."""
    latitude1, latitude2 = math.radians(lat1), math.radians(lat2)
    latitude_delta = latitude2 - latitude1
    longitude_delta = math.radians(lon2 - lon1)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude1) * math.cos(latitude2) * math.sin(longitude_delta / 2) ** 2
    )
    # Floating-point rounding near antipodes can otherwise put sqrt outside [0,1].
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def build_risk_snapshot(
    fires: list[FireEvent], occurrences: list[WildlifeOccurrence], *,
    mode: DataMode, fetched_at: datetime, truncated: bool,
) -> RiskResponse:
    """Rank nearby observations without inferring movement, ETA, or animal presence."""
    candidates = []
    if fires:
        for occurrence in occurrences:
            distance, _, nearest_fire = min(
                ((distance_km(occurrence.latitude, occurrence.longitude, fire.latitude, fire.longitude), fire.id, fire)
                 for fire in fires),
                key=lambda item: (item[0], item[1]),
            )
            if distance <= CANDIDATE_RADIUS_KM:
                candidates.append(ZoneAssessment(
                    id=f"gbif:{occurrence.id}", name=f"Observation {occurrence.id}",
                    latitude=occurrence.latitude, longitude=occurrence.longitude,
                    species=occurrence.species, nearest_fire_id=nearest_fire.id,
                    distance_to_fire_km=distance,
                    risk=max(0.0, 1 - distance / CANDIDATE_RADIUS_KM), risk_method="proximity",
                    fire_eta_minutes=None, response_time_minutes=None, safety_buffer_minutes=None,
                    response_window_minutes=None, priority="UNASSESSED",
                ))
    candidates.sort(key=lambda candidate: (-candidate.risk, candidate.id))
    return RiskResponse(
        fires=fires, occurrences=occurrences, wildlife_zones=candidates,
        mode=mode, fetched_at=fetched_at, truncated=truncated,
    )


def evaluate_scenario(scenario: TimingScenario) -> ScenarioResponse:
    """Replace posted timing/priority with calculations from explicit operator input."""
    window = calculate_response_window(
        scenario.fire_eta_minutes, scenario.response_time_minutes, scenario.safety_buffer_minutes,
    )
    assessment = ZoneAssessment.model_validate({
        **scenario.zone.model_dump(),
        "fire_eta_minutes": scenario.fire_eta_minutes,
        "response_time_minutes": scenario.response_time_minutes,
        "safety_buffer_minutes": scenario.safety_buffer_minutes,
        "response_window_minutes": window,
        "priority": calculate_priority(scenario.zone.risk, window),
    })
    return ScenarioResponse(assessment=assessment, timing_source="operator_scenario")
