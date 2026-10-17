"""Offline GBIF adapter boundary tests; only the HTTP transport is replaced."""

from copy import deepcopy
import json
from pathlib import Path
import traceback

import pytest
import requests

from app.config import Settings
from app.services.errors import ProviderError
from app.services.gbif import fetch_occurrences


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "gbif.json").read_text(encoding="utf-8-sig"))


class FixtureSession:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        response = requests.Response()
        response.url = url + "?secret=must-not-leak"
        response.status_code = page if isinstance(page, int) else 200
        if page == "bad-json":
            response._content = b"not json: must-not-leak"
        else:
            # Parsed-payload tests must reach the row validator even when
            # requests selects a strict JSON decoder such as simplejson.
            response._content = b"{}"
            response.json = lambda **_kwargs: deepcopy(page)
        return response


def settings(**kwargs):
    return Settings(firms_map_key="offline-test-key", **kwargs)


def page(rows=None, *, offset=0, end=True):
    return {
        "offset": offset,
        "limit": 100,
        "endOfRecords": end,
        "count": offset + len(rows or []) if end else 1000,
        "results": rows or [],
    }


def row(**kwargs):
    return {**deepcopy(FIXTURE["results"][0]), **kwargs}


def test_preserves_observation_source_date_and_attribution():
    occurrences, truncated = fetch_occurrences(settings(), FixtureSession(FIXTURE))
    assert truncated is False
    assert [item.model_dump() for item in occurrences] == [{
        "id": "5938026320", "species": "Nymphalis californica",
        "latitude": 38.114101, "longitude": -122.600098,
        "observed_at": "2026-01-07",
        "dataset_key": "cf3bdc30-370c-48d3-8fff-b587a39d72d6",
        "license": "http://creativecommons.org/licenses/by-nc/4.0/legalcode", "source": "GBIF",
    }]


def test_queries_configured_bbox_with_coordinate_filter_and_timeout():
    session = FixtureSession(page())
    assert fetch_occurrences(settings(bbox=(-120, 33, -117, 36)), session) == ([], False)
    assert session.calls == [("https://api.gbif.org/v1/occurrence/search", {
        "params": {"hasCoordinate": "true", "kingdomKey": 1, "decimalLatitude": "33,36",
                   "decimalLongitude": "-120,-117", "limit": 100, "offset": 0},
        "timeout": (3.05, 10),
    })]


def test_precise_custom_bbox_preserves_all_request_boundaries():
    session = FixtureSession(page())
    fetch_occurrences(
        settings(bbox=(-120.123456, 33.123451, -120.123451, 33.123456)), session,
    )
    params = session.calls[0][1]["params"]
    assert params["decimalLatitude"] == "33.123451,33.123456"
    assert params["decimalLongitude"] == "-120.123456,-120.123451"


@pytest.mark.parametrize("date", [None, "2020", "2020-04", "2020-04-03T12:30:00Z", "2020-01/2020-03"])
def test_partial_and_missing_dates_do_not_gain_precision(date):
    occurrences, _ = fetch_occurrences(settings(), FixtureSession(page([row(eventDate=date)])))
    assert occurrences[0].observed_at == date


def test_missing_optional_source_fields_remain_null():
    occurrence = row()
    for field in ("eventDate", "datasetKey", "license"):
        occurrence.pop(field)
    occurrences, _ = fetch_occurrences(settings(), FixtureSession(page([occurrence])))
    assert occurrences[0].observed_at is None
    assert occurrences[0].dataset_key is None
    assert occurrences[0].license is None


@pytest.mark.parametrize("species,scientific,want", [
    (None, "Puma concolor (Linnaeus, 1771)", "Puma concolor (Linnaeus, 1771)"),
    (" ", "Puma concolor", "Puma concolor"),
    (None, None, "Unknown species"),
    ("", "", "Unknown species"),
    (12, {"invalid": "label"}, "Unknown species"),
])
def test_missing_species_keeps_location_with_fallback(species, scientific, want):
    occurrences, _ = fetch_occurrences(settings(), FixtureSession(page([
        row(species=species, scientificName=scientific)])))
    assert len(occurrences) == 1
    assert occurrences[0].species == want


@pytest.mark.parametrize("changes", [
    {"decimalLatitude": None}, {"decimalLongitude": None},
    {"decimalLatitude": ""}, {"decimalLongitude": "bad"},
    {"decimalLatitude": True}, {"decimalLongitude": False},
    {"decimalLatitude": 91}, {"decimalLongitude": -181},
    {"decimalLatitude": float("nan")}, {"decimalLongitude": float("inf")},
    {"decimalLatitude": 30}, {"decimalLongitude": -130},
    {"key": None}, {"key": ""}, {"key": True}, {"key": []},
    {"eventDate": []}, {"datasetKey": {}}, {"license": 5},
])
def test_skips_unusable_rows_without_losing_valid_rows(changes):
    invalid = row(key=1)
    invalid.update(changes)
    occurrences, truncated = fetch_occurrences(settings(), FixtureSession(page([
        invalid, None, "not a record", row(),
    ])))
    assert [item.id for item in occurrences] == ["5938026320"]
    assert truncated is False


def test_skips_row_with_missing_required_coordinate():
    invalid = row(key=1)
    invalid.pop("decimalLatitude")
    occurrences, _ = fetch_occurrences(settings(), FixtureSession(page([invalid, row()])))
    assert [item.id for item in occurrences] == ["5938026320"]


def test_configured_bbox_edges_are_inclusive():
    rows = [row(key=i, decimalLatitude=lat, decimalLongitude=lon)
            for i, (lat, lon) in enumerate([(33, -120), (36, -117)], start=1)]
    occurrences, _ = fetch_occurrences(settings(bbox=(-120, 33, -117, 36)), FixtureSession(page(rows)))
    assert [item.id for item in occurrences] == ["1", "2"]


def test_deduplicates_gbif_keys_within_and_across_pages():
    session = FixtureSession(page([row(), row()], end=False),
                             page([row(key="5938026320"), row(key=2)], offset=100))
    occurrences, truncated = fetch_occurrences(settings(), session)
    assert [item.id for item in occurrences] == ["5938026320", "2"]
    assert truncated is False
    assert [call[1]["params"]["offset"] for call in session.calls] == [0, 100]


@pytest.mark.parametrize("last_page_ends,want_truncated", [(False, True), (True, False)])
def test_consumes_at_most_three_pages(last_page_ends, want_truncated):
    session = FixtureSession(page([row(key=1)], end=False),
                             page([row(key=2)], offset=100, end=False),
                             page([row(key=3)], offset=200, end=last_page_ends))
    occurrences, truncated = fetch_occurrences(settings(), session)
    assert [item.id for item in occurrences] == ["1", "2", "3"]
    assert truncated is want_truncated
    assert [call[1]["params"]["offset"] for call in session.calls] == [0, 100, 200]


@pytest.mark.parametrize("payload", [
    None, [], {}, {"results": []},
    page() | {"results": {}}, page() | {"endOfRecords": "false"},
    page() | {"offset": 100}, page() | {"offset": False},
    page() | {"limit": "100"}, page() | {"limit": 0},
    page() | {"count": -1}, page() | {"count": True},
    page() | {"endOfRecords": 1}, page([row()] * 101),
])
def test_unrecognisable_envelope_is_failure_not_empty_success(payload):
    with pytest.raises(ProviderError):
        fetch_occurrences(settings(), FixtureSession(payload))


@pytest.mark.parametrize("failure", [
    requests.Timeout("must-not-leak https://example.test/?key=secret"),
    requests.ConnectionError("must-not-leak"), 429, 503, "bad-json",
])
@pytest.mark.parametrize("later_page", [False, True])
def test_upstream_failures_are_sanitized_and_never_return_partial_success(failure, later_page):
    pages = [page([row()], end=False), failure] if later_page else [failure]
    session = FixtureSession(*pages)
    with pytest.raises(ProviderError) as error:
        fetch_occurrences(settings(), session)
    assert "GBIF" in str(error.value)
    assert "must-not-leak" not in "".join(traceback.format_exception(error.value))
    assert "secret" not in str(error.value)
    assert len(session.calls) == (2 if later_page else 1)


def test_later_malformed_envelope_does_not_return_partial_success():
    with pytest.raises(ProviderError):
        fetch_occurrences(settings(), FixtureSession(page([row()], end=False), {}))


def test_explicit_sample_mode_returns_deterministic_observations_without_network():
    session = FixtureSession()
    first = fetch_occurrences(settings(data_mode="sample"), session)
    second = fetch_occurrences(settings(data_mode="sample"), session)
    assert first == second
    assert first[1] is False
    assert len(first[0]) >= 1
    assert all(item.source == "GBIF" for item in first[0])
    assert session.calls == []



def test_animalia_filter_is_sent_on_every_page():
    session = FixtureSession(page([row(key=1)], end=False),
                             page([row(key=2)], offset=100, end=False),
                             page([row(key=3)], offset=200, end=False))
    occurrences, truncated = fetch_occurrences(settings(), session)
    assert [item.id for item in occurrences] == ["1", "2", "3"]
    assert truncated is True
    assert [call[1]["params"]["offset"] for call in session.calls] == [0, 100, 200]
    assert [call[1]["params"].get("kingdomKey") for call in session.calls] == [1, 1, 1]


@pytest.mark.parametrize("kingdom_key", [5, 6, None, True, False, "1", 1.0, {}, []])
def test_unconfirmed_or_non_animal_classification_is_excluded(kingdom_key):
    occurrences, truncated = fetch_occurrences(settings(), FixtureSession(page([
        row(key=1, kingdomKey=kingdom_key), row(),
    ])))
    assert [item.id for item in occurrences] == ["5938026320"]
    assert truncated is False


def test_missing_kingdom_classification_is_excluded():
    unclassified = row(key=1)
    unclassified.pop("kingdomKey")
    occurrences, _ = fetch_occurrences(settings(), FixtureSession(page([unclassified, row()])))
    assert [item.id for item in occurrences] == ["5938026320"]


def test_mixed_kingdoms_cannot_become_wildlife_or_shadow_a_later_animal():
    session = FixtureSession(
        page([row(kingdomKey=5, kingdom="Fungi", species="Collybia"),
              row(key=2, kingdomKey=6, kingdom="Plantae", species="Synthetic plant")], end=False),
        page([row()], offset=100),
    )
    occurrences, truncated = fetch_occurrences(settings(), session)
    assert [item.id for item in occurrences] == ["5938026320"]
    assert occurrences[0].species == "Nymphalis californica"
    assert truncated is False
