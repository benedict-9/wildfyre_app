import pytest


def test_sample_settings_defaults_and_secret_repr():
    from app.config import load_settings

    settings = load_settings({"WILDFYRE_DATA_MODE": "sample", "FIRMS_MAP_KEY": "private-key"})
    assert settings.bbox == (-124.5, 32.5, -114.0, 42.1)
    assert settings.firms_source == "VIIRS_SNPP_NRT"
    assert settings.allowed_origins == ("http://127.0.0.1:8080", "http://localhost:8080")
    assert "private-key" not in repr(settings)
    assert load_settings({"WILDFYRE_DATA_MODE": "sample"}).firms_map_key is None


def test_live_default_requires_a_map_key_without_exposing_it():
    from app.config import load_settings

    with pytest.raises(ValueError, match="FIRMS_MAP_KEY"):
        load_settings({})
    assert load_settings({"FIRMS_MAP_KEY": "test-key"}).data_mode == "live"


@pytest.mark.parametrize("overrides", [
    {"WILDFYRE_DATA_MODE": "invalid"},
    {"WILDFYRE_BBOX": "1,2,3"},
    {"WILDFYRE_BBOX": "1,2,nan,4"},
    {"WILDFYRE_BBOX": "1,2,181,4"},
    {"WILDFYRE_BBOX": "1,-91,2,4"},
    {"WILDFYRE_BBOX": "3,2,1,4"},
    {"WILDFYRE_BBOX": "1,4,2,2"},
    {"WILDFYRE_BBOX": "1,2,1,4"},
    {"FIRMS_SOURCE": "../secret"},
    {"WILDFYRE_ALLOWED_ORIGINS": "*"},
    {"WILDFYRE_ALLOWED_ORIGINS": "https://example.com/path"},
])
def test_settings_reject_invalid_environment(overrides):
    from app.config import load_settings

    with pytest.raises(ValueError):
        load_settings({"WILDFYRE_DATA_MODE": "sample", **overrides})


def test_settings_validate_direct_construction_and_parse_overrides():
    from app.config import Settings, load_settings

    with pytest.raises(ValueError):
        Settings(data_mode="live", firms_map_key=None)
    settings = load_settings({"WILDFYRE_DATA_MODE": "sample", "WILDFYRE_BBOX": "-2,1,3,4", "WILDFYRE_ALLOWED_ORIGINS": " https://example.com ,http://localhost:9000 "})
    assert settings.bbox == (-2, 1, 3, 4)
    assert settings.allowed_origins == ("https://example.com", "http://localhost:9000")

@pytest.mark.parametrize("overrides", [
    {"firms_map_key": 123},
    {"firms_map_key": "   "},
    {"bbox": (True, 0, 2, 1)},
])
def test_direct_settings_reject_invalid_field_types_and_blank_keys(overrides):
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(**{"firms_map_key": "test-key", **overrides})
