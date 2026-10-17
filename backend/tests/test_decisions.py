"""Decision rules tested independently of HTTP and provider parsing."""
from datetime import datetime, timezone
from importlib import import_module
import math

import pytest

from app.schemas import FireEvent, TimingScenario, WildlifeOccurrence, ZoneAssessment

NOW = datetime(2026, 10, 17, 4, tzinfo=timezone.utc)


def fire(id="fire-1", latitude=34.0, longitude=-118.0):
    return FireEvent(id=id, latitude=latitude, longitude=longitude,
                     observed_at=NOW, frp_mw=None, source="NASA FIRMS")


def occurrence(id="1", latitude=34.0, longitude=-118.0):
    return WildlifeOccurrence(id=id, latitude=latitude, longitude=longitude,
                              species="Mountain Lion", observed_at="2020-05",
                              dataset_key="dataset", license="CC0", source="GBIF")


def zone(**kwargs):
    return ZoneAssessment.model_validate({
        "id": "gbif:1", "name": "Observation 1", "latitude": 34, "longitude": -118,
        "species": "Mountain Lion", "nearest_fire_id": "fire-1", "distance_to_fire_km": 2.25,
        "risk": 0.91, "risk_method": "proximity", "fire_eta_minutes": None,
        "response_time_minutes": None, "safety_buffer_minutes": None,
        "response_window_minutes": None, "priority": "UNASSESSED", **kwargs,
    })


def decisions():
    return import_module("app.services.decisions")


def snapshot(fires, occurrences, **kwargs):
    return decisions().build_risk_snapshot(
        fires, occurrences, mode="live", fetched_at=NOW, truncated=True, **kwargs,
    )


@pytest.mark.parametrize("points,want", [
    ((34, -118, 34, -118), 0),
    ((0, 0, 0, 1), 111.195),
    ((0, 179.5, 0, -179.5), 111.195),
    ((90, 0, -90, 180), 20015.114),
])
def test_great_circle_distance_handles_identity_equator_antimeridian_and_antipodes(points, want):
    assert decisions().distance_km(*points) == pytest.approx(want, abs=0.001)


@pytest.mark.parametrize("distance,want", [(0, 1), (12.5, 0.5), (25, 0)])
def test_candidate_scores_and_inclusive_radius_use_unrounded_distance(monkeypatch, distance, want):
    monkeypatch.setattr(decisions(), "distance_km", lambda *args: distance)
    result = snapshot([fire()], [occurrence()])
    assert len(result.wildlife_zones) == 1
    candidate = result.wildlife_zones[0]
    assert candidate.distance_to_fire_km == distance
    assert candidate.risk == want
    assert candidate.id == "gbif:1"
    assert candidate.name == "Observation 1"
    assert candidate.species == "Mountain Lion"
    assert candidate.risk_method == "proximity"
    assert candidate.nearest_fire_id == "fire-1"


def test_just_outside_radius_is_not_a_candidate_but_raw_record_survives(monkeypatch):
    monkeypatch.setattr(decisions(), "distance_km", lambda *args: math.nextafter(25, math.inf))
    raw = occurrence()
    result = snapshot([fire()], [raw])
    assert result.wildlife_zones == []
    assert result.occurrences == [raw]


def test_nearest_fire_is_selected_from_all_detections():
    result = snapshot([fire("distant", longitude=-118.15), fire("nearest")], [occurrence()])
    assert result.wildlife_zones[0].nearest_fire_id == "nearest"
    assert result.wildlife_zones[0].distance_to_fire_km == 0
    assert result.wildlife_zones[0].risk == 1


def test_candidate_order_is_score_descending_then_id():
    result = snapshot([fire()], [occurrence("3", longitude=-118.01), occurrence("2"), occurrence("1")])
    assert [item.id for item in result.wildlife_zones] == ["gbif:1", "gbif:2", "gbif:3"]


@pytest.mark.parametrize("fires,occurrences", [([], []), ([fire()], []), ([], [occurrence()])])
def test_empty_provider_results_preserve_raw_records_and_metadata(fires, occurrences):
    result = snapshot(fires, occurrences)
    assert result.wildlife_zones == []
    assert result.fires == fires
    assert result.occurrences == occurrences
    assert result.mode == "live"
    assert result.fetched_at == NOW
    assert result.truncated is True


@pytest.mark.parametrize("mode", ["live", "sample"])
def test_detection_and_observation_alone_never_invent_timing(mode):
    result = decisions().build_risk_snapshot([fire()], [occurrence()], mode=mode, fetched_at=NOW, truncated=False)
    candidate = result.wildlife_zones[0]
    assert candidate.priority == "UNASSESSED"
    for field in ("fire_eta_minutes", "response_time_minutes", "safety_buffer_minutes", "response_window_minutes"):
        assert getattr(candidate, field) is None


@pytest.mark.parametrize("eta,response,buffer,risk,window,priority", [
    (95, 40, 20, 0.91, 35, "CRITICAL"),
    (60, 40, 20, 0.91, 0, "ALTERNATIVE RESPONSE"),
    (50, 40, 20, 0.91, -10, "ALTERNATIVE RESPONSE"),
    (60.5, 40.25, 20, 0.5, 0.25, "HIGH"),
    (95, 40, 20, 0.49, 35, "MODERATE"),
])
def test_scenario_recomputes_posted_priority_and_window_without_mutating_zone(eta, response, buffer, risk, window, priority):
    candidate = zone(risk=risk, priority="HIGH", response_window_minutes=999,
                     fire_eta_minutes=999, response_time_minutes=888, safety_buffer_minutes=777)
    original = candidate.model_dump()
    result = decisions().evaluate_scenario(TimingScenario(
        zone=candidate, fire_eta_minutes=eta, response_time_minutes=response, safety_buffer_minutes=buffer,
    ))
    assert result.timing_source == "operator_scenario"
    assert result.assessment.response_window_minutes == window
    assert result.assessment.priority == priority
    assert result.assessment.fire_eta_minutes == eta
    assert result.assessment.response_time_minutes == response
    assert result.assessment.safety_buffer_minutes == buffer
    assert result.assessment.risk == risk
    assert result.assessment.id == "gbif:1"
    assert candidate.model_dump() == original


def test_duplicate_fire_identity_with_different_frp_still_selects_a_nearest_fire():
    first = fire()
    duplicate = first.model_copy(update={"frp_mw": 12.5})
    result = snapshot([first, duplicate], [occurrence()])
    assert result.wildlife_zones[0].nearest_fire_id == "fire-1"
    assert result.wildlife_zones[0].distance_to_fire_km == 0
