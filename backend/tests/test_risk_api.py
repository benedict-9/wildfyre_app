"""Combined route contracts with real adapters and offline provider transports."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
import pytest
import requests

from app.config import Settings
from app.main import create_app, get_session
from test_decisions import zone
from test_firms import FixtureSession as FirmsSession, HEADER
from test_gbif import FixtureSession as GbifSession, page, row


class ProviderSession:
    def __init__(self, *, firms=None, pages=None):
        self.firms = firms if firms is not None else FirmsSession()
        self.gbif = GbifSession(*(pages if pages is not None else [page([row(
            key=1, decimalLatitude=34.22, decimalLongitude=-118.55, eventDate="2020-05",
        )])]))

    def get(self, url, **kwargs):
        if url.startswith("https://firms.modaps.eosdis.nasa.gov/"):
            return self.firms.get(url, **kwargs)
        if url == "https://api.gbif.org/v1/occurrence/search":
            return self.gbif.get(url, **kwargs)
        raise AssertionError("Unexpected provider")


def live_app(session):
    application = create_app(Settings(firms_map_key="test-secret"))
    application.dependency_overrides[get_session] = lambda: session
    return application


def assert_utc_retrieval_time(payload, before, after):
    timestamp = datetime.fromisoformat(payload["fetched_at"])
    assert timestamp.utcoffset().total_seconds() == 0
    assert before <= timestamp <= after


def test_risk_fetches_each_provider_once_and_preserves_raw_records():
    session = ProviderSession()
    before = datetime.now(timezone.utc)
    with TestClient(live_app(session)) as client:
        response = client.get("/risk")
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "live"
    assert payload["truncated"] is False
    assert_utc_retrieval_time(payload, before, after)
    assert len(session.firms.calls) == 1
    assert len(session.gbif.calls) == 1
    assert len(payload["fires"]) == 2
    assert len(payload["occurrences"]) == 1
    assert payload["occurrences"][0]["observed_at"] == "2020-05"
    assert payload["occurrences"][0]["source"] == "GBIF"
    assert payload["occurrences"][0]["dataset_key"] is not None
    candidate = payload["wildlife_zones"][0]
    assert candidate["id"] == "gbif:1"
    assert candidate["risk"] == 1
    assert candidate["distance_to_fire_km"] == 0
    assert candidate["nearest_fire_id"] == payload["fires"][0]["id"]
    assert candidate["priority"] == "UNASSESSED"
    for field in ("fire_eta_minutes", "response_time_minutes", "safety_buffer_minutes", "response_window_minutes"):
        assert candidate[field] is None


@pytest.mark.parametrize("route", ["/risk", "/wildlife"])
def test_routes_preserve_bounded_gbif_truncation(route):
    pages = [page([row(key=number + 1)], offset=number * 100, end=False) for number in range(3)]
    session = ProviderSession(pages=pages)
    with TestClient(live_app(session)) as client:
        response = client.get(route)
    assert response.status_code == 200
    payload = response.json()
    assert payload["truncated"] is True
    assert len(payload["occurrences"]) == 3
    assert len(session.gbif.calls) == 3
    assert len(session.firms.calls) == (1 if route == "/risk" else 0)


@pytest.mark.parametrize("empty_fires,empty_occurrences", [(True, False), (False, True), (True, True)])
def test_risk_empty_success_keeps_each_provider_result(empty_fires, empty_occurrences):
    session = ProviderSession(
        firms=FirmsSession(HEADER) if empty_fires else None,
        pages=[page()] if empty_occurrences else None,
    )
    with TestClient(live_app(session)) as client:
        response = client.get("/risk")
    assert response.status_code == 200
    payload = response.json()
    assert payload["wildlife_zones"] == []
    assert len(payload["fires"]) == (0 if empty_fires else 2)
    assert len(payload["occurrences"]) == (0 if empty_occurrences else 1)
    assert payload["mode"] == "live"
    assert payload["truncated"] is False


@pytest.mark.parametrize("failure", ["firms", "gbif", "gbif-later"])
def test_risk_returns_sanitized_503_without_partial_success_or_sample_fallback(failure):
    error = requests.Timeout("https://secret.example/test-secret")
    session = ProviderSession(
        firms=FirmsSession(error=error) if failure == "firms" else None,
        pages=[error] if failure == "gbif" else [page([row()], end=False), error] if failure == "gbif-later" else None,
    )
    with TestClient(live_app(session)) as client:
        response = client.get("/risk")
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "test-secret" not in response.text
    assert "https://" not in response.text
    assert "sample" not in response.text


@pytest.mark.parametrize("mode", ["live", "sample"])
def test_wildlife_metadata_preserves_source_dates_and_never_fetches_fires(mode):
    session = ProviderSession()
    application = create_app(Settings(data_mode=mode, firms_map_key="test-secret"))
    application.dependency_overrides[get_session] = lambda: session
    before = datetime.now(timezone.utc)
    with TestClient(application) as client:
        response = client.get("/wildlife")
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == mode
    assert payload["truncated"] is False
    assert payload["occurrences"][0]["observed_at"] == "2020-05"
    assert payload["occurrences"][0]["source"] == "GBIF"
    assert_utc_retrieval_time(payload, before, after)
    assert session.firms.calls == []
    assert len(session.gbif.calls) == (1 if mode == "live" else 0)


def test_wildlife_empty_success_is_distinct_from_sanitized_failure():
    session = ProviderSession(pages=[page(), requests.Timeout("test-secret https://secret")])
    with TestClient(live_app(session)) as client:
        empty = client.get("/wildlife")
        failed = client.get("/wildlife")
    assert empty.status_code == 200
    assert empty.json()["occurrences"] == []
    assert failed.status_code == 503
    assert set(failed.json()) == {"detail"}
    assert "test-secret" not in failed.text
    assert "https://" not in failed.text


def scenario_payload():
    return dict(zone=zone(priority="MODERATE", response_window_minutes=999).model_dump(mode="json"),
                fire_eta_minutes=95, response_time_minutes=40, safety_buffer_minutes=20)


def test_evaluate_is_stateless_uses_operator_values_and_makes_no_provider_requests():
    application = create_app(Settings(firms_map_key="test-secret"))

    def no_session():
        pytest.fail("Scenario evaluation must not acquire a provider session")

    application.dependency_overrides[get_session] = no_session
    payload = scenario_payload()
    original = deepcopy(payload)
    with TestClient(application) as client:
        first = client.post("/risk/evaluate", json=payload)
        second = client.post("/risk/evaluate", json={**payload, "fire_eta_minutes": 50})
    assert first.status_code == 200
    result = first.json()
    assert result["timing_source"] == "operator_scenario"
    assert result["assessment"]["response_window_minutes"] == 35
    assert result["assessment"]["priority"] == "CRITICAL"
    assert second.status_code == 200
    assert second.json()["assessment"]["response_window_minutes"] == -10
    assert second.json()["assessment"]["priority"] == "ALTERNATIVE RESPONSE"
    assert payload == original


@pytest.mark.parametrize("field", ["fire_eta_minutes", "response_time_minutes", "safety_buffer_minutes"])
@pytest.mark.parametrize("value", [-1, True, False, None, "95", float("nan"), float("inf"), -float("inf")])
def test_evaluate_rejects_invalid_durations_with_422(field, value):
    payload = {**scenario_payload(), field: value}
    with TestClient(create_app(Settings(data_mode="sample"))) as client:
        response = client.post("/risk/evaluate", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("field,value", [
    ("latitude", 91), ("longitude", -181), ("latitude", True), ("longitude", float("nan")),
    ("risk", -0.1), ("risk", 1.1), ("risk", True), ("risk", float("inf")),
    ("distance_to_fire_km", -1), ("distance_to_fire_km", False),
    ("response_window_minutes", float("nan")), ("fire_eta_minutes", -1),
    ("priority", "URGENT"), ("risk_method", "prediction"),
])
def test_evaluate_validates_posted_zone_fields(field, value):
    payload = scenario_payload()
    payload["zone"][field] = value
    with TestClient(create_app(Settings(data_mode="sample"))) as client:
        response = client.post("/risk/evaluate", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_evaluate_returns_422_when_finite_durations_overflow_the_window():
    payload = {**scenario_payload(), "fire_eta_minutes": 0,
               "response_time_minutes": 1e308, "safety_buffer_minutes": 1e308}
    with TestClient(create_app(Settings(data_mode="sample"))) as client:
        response = client.post("/risk/evaluate", json=payload)
    assert response.status_code == 422
