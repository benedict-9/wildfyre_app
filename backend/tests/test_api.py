from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_project_status():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"project": "WildFyre", "status": "running"}


def test_risk_returns_explicit_sample_mode_with_unknown_timing():
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_mode="sample"))) as sample_client:
        response = sample_client.get("/risk")
    assert response.status_code == 200
    payload = response.json()
    assert "fire" not in payload
    assert payload["mode"] == "sample"
    assert payload["truncated"] is False
    assert payload["fires"][0]["id"] == "sample-fire-1"
    assert len(payload["occurrences"]) == 2
    assert payload["fetched_at"].endswith("Z")
    assert {item["id"] for item in payload["wildlife_zones"]} == {"gbif:sample-1", "gbif:sample-2"}
    for candidate in payload["wildlife_zones"]:
        assert candidate["priority"] == "UNASSESSED"
        for field in ("fire_eta_minutes", "response_time_minutes", "safety_buffer_minutes", "response_window_minutes"):
            assert candidate[field] is None


def test_fires_route_returns_explicit_sample_metadata():
    from app.config import load_settings
    from app.main import create_app

    with TestClient(create_app(load_settings({"WILDFYRE_DATA_MODE": "sample"}))) as sample_client:
        response = sample_client.get("/fires")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "sample"
    assert payload["fires"][0]["id"] == "sample-fire-1"
    assert payload["fetched_at"].endswith("Z")


def test_startup_validates_live_configuration_without_a_key(monkeypatch):
    import pytest
    from app.main import create_app

    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    monkeypatch.delenv("WILDFYRE_DATA_MODE", raising=False)
    with pytest.raises(ValueError, match="FIRMS_MAP_KEY"):
        with TestClient(create_app()):
            pass


def test_fires_route_sanitizes_provider_failure_without_fallback():
    from app.config import load_settings
    from app.main import create_app, get_session
    from test_firms import FixtureSession
    import requests

    live_app = create_app(load_settings({"FIRMS_MAP_KEY": "test-secret"}))
    live_app.dependency_overrides[get_session] = lambda: FixtureSession(error=requests.Timeout("https://url/test-secret"))
    with TestClient(live_app) as live_client:
        response = live_client.get("/fires")
    assert response.status_code == 503
    assert "test-secret" not in response.text
    assert "https://" not in response.text
    assert "fires" not in response.json()


def test_fires_route_returns_normalized_live_and_empty_results():
    from app.config import load_settings
    from app.main import create_app, get_session
    from test_firms import FixtureSession, HEADER

    live_app = create_app(load_settings({"FIRMS_MAP_KEY": "test-secret"}))
    with TestClient(live_app) as live_client:
        live_app.dependency_overrides[get_session] = lambda: FixtureSession()
        response = live_client.get("/fires")
        assert response.status_code == 200
        assert response.json()["mode"] == "live"
        assert response.json()["fires"][0]["frp_mw"] == 12.5
        live_app.dependency_overrides[get_session] = lambda: FixtureSession(HEADER)
        assert live_client.get("/fires").json()["fires"] == []


def test_cors_uses_configured_origins_without_credentials():
    from app.config import load_settings
    from app.main import create_app

    sample_app = create_app(load_settings({"WILDFYRE_DATA_MODE": "sample", "WILDFYRE_ALLOWED_ORIGINS": "https://map.example.com"}))
    with TestClient(sample_app) as sample_client:
        allowed = sample_client.get("/", headers={"Origin": "https://map.example.com"})
        denied = sample_client.get("/", headers={"Origin": "https://other.example.com"})
    assert allowed.headers["access-control-allow-origin"] == "https://map.example.com"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in denied.headers
