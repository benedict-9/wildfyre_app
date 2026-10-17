from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_normalized_sample_records_match_shared_schemas():
    from app.data import sample_fire_events, sample_wildlife_occurrences
    from app.schemas import FireEvent, WildlifeOccurrence

    fires = [FireEvent.model_validate(row) for row in sample_fire_events]
    occurrences = [WildlifeOccurrence.model_validate(row) for row in sample_wildlife_occurrences]
    assert fires and occurrences
    assert fires[0].observed_at.utcoffset().total_seconds() == 0
    assert occurrences[0].observed_at is not None


@pytest.mark.parametrize("field,value", [("latitude", 91), ("longitude", -181), ("latitude", float("nan")), ("frp_mw", float("inf")), ("observed_at", "2026-10-17T12:00:00")])
def test_fire_rejects_invalid_coordinates_frp_or_naive_time(field, value):
    from app.schemas import FireEvent

    row = dict(id="f", latitude=34.0, longitude=-118.0, observed_at="2026-10-17T12:00:00Z", frp_mw=None, source="NASA FIRMS")
    with pytest.raises(ValidationError):
        FireEvent.model_validate({**row, field: value})


def test_shared_schemas_preserve_partial_dates_and_normalize_utc():
    from app.schemas import FireEvent, FireResponse, WildlifeOccurrence, WildlifeResponse, RiskResponse, ZoneAssessment, TimingScenario, ScenarioResponse

    fire = FireEvent(id="f", latitude=34, longitude=-118, observed_at="2026-10-17T12:00:00+08:00", frp_mw=None, source="NASA FIRMS")
    occurrence = WildlifeOccurrence(id="1", species="Lion", latitude=34, longitude=-118, observed_at="2020-05", dataset_key=None, license=None, source="GBIF")
    assert fire.observed_at.hour == 4
    assert occurrence.observed_at == "2020-05"
    now = datetime.now(timezone.utc)
    assert FireResponse(fires=[fire], mode="sample", fetched_at=now).fires == [fire]
    assert WildlifeResponse(occurrences=[occurrence], mode="sample", fetched_at=now, truncated=False).truncated is False
    assert RiskResponse(fires=[fire], occurrences=[occurrence], wildlife_zones=[], mode="sample", fetched_at=now, truncated=False).wildlife_zones == []
    zone = ZoneAssessment(id="gbif:1", name="Observation 1", latitude=34, longitude=-118, species="Lion", nearest_fire_id="f", distance_to_fire_km=0, risk=1, risk_method="proximity", fire_eta_minutes=None, response_time_minutes=None, safety_buffer_minutes=None, response_window_minutes=None, priority="UNASSESSED")
    assert ScenarioResponse(assessment=zone, timing_source="operator_scenario").assessment.priority == "UNASSESSED"
    for value in [-1, float("nan"), float("inf")]:
        with pytest.raises(ValidationError):
            TimingScenario(zone=zone, fire_eta_minutes=value, response_time_minutes=0, safety_buffer_minutes=0)
    for field,value in [("risk",1.1),("distance_to_fire_km",-1),("response_window_minutes",float("inf")),("latitude",float("nan"))]:
        with pytest.raises(ValidationError):
            ZoneAssessment.model_validate({**zone.model_dump(),field:value})

# Every public numeric field must distinguish JSON booleans from real numbers.
NUMERIC_FIELDS = [
    ("FireEvent", "latitude"), ("FireEvent", "longitude"), ("FireEvent", "frp_mw"),
    ("WildlifeOccurrence", "latitude"), ("WildlifeOccurrence", "longitude"),
    ("ZoneAssessment", "latitude"), ("ZoneAssessment", "longitude"),
    ("ZoneAssessment", "distance_to_fire_km"), ("ZoneAssessment", "risk"),
    ("ZoneAssessment", "fire_eta_minutes"), ("ZoneAssessment", "response_time_minutes"),
    ("ZoneAssessment", "safety_buffer_minutes"), ("ZoneAssessment", "response_window_minutes"),
    ("TimingScenario", "fire_eta_minutes"), ("TimingScenario", "response_time_minutes"),
    ("TimingScenario", "safety_buffer_minutes"),
]


def numeric_payload(model_name):
    zone = dict(
        id="gbif:1", name="Observation 1", latitude=34, longitude=-118,
        species="Lion", nearest_fire_id="f", distance_to_fire_km=0, risk=1,
        risk_method="proximity", fire_eta_minutes=None, response_time_minutes=None,
        safety_buffer_minutes=None, response_window_minutes=None, priority="UNASSESSED",
    )
    return {
        "FireEvent": dict(id="f", latitude=34, longitude=-118,
                          observed_at="2026-10-17T12:00:00Z", frp_mw=None, source="NASA FIRMS"),
        "WildlifeOccurrence": dict(id="1", species="Lion", latitude=34, longitude=-118,
                                   observed_at=None, dataset_key=None, license=None, source="GBIF"),
        "ZoneAssessment": zone,
        "TimingScenario": dict(zone=zone, fire_eta_minutes=95,
                               response_time_minutes=40, safety_buffer_minutes=20),
    }[model_name]


@pytest.mark.parametrize("model_name,field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", [False, True])
def test_shared_numeric_fields_reject_json_booleans(model_name, field, value):
    import json
    from app import schemas

    payload = {**numeric_payload(model_name), field: value}
    with pytest.raises(ValidationError):
        getattr(schemas, model_name).model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("model_name,field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", [1, 0.5])
def test_shared_numeric_fields_preserve_legitimate_ints_and_floats(model_name, field, value):
    import json
    from app import schemas

    payload = {**numeric_payload(model_name), field: value}
    result = getattr(schemas, model_name).model_validate_json(json.dumps(payload))
    assert getattr(result, field) == value
