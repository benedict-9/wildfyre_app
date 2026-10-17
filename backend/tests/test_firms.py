from pathlib import Path
from datetime import datetime, timezone

import pytest
import requests

from app.config import load_settings
from app.services.errors import ProviderError

FIXTURE = Path(__file__).parent / "fixtures" / "firms.csv"
HEADER = "latitude,longitude,acq_date,acq_time,frp\n"


class FixtureSession:
    def __init__(self, text=None, status=200, error=None):
        self.text = FIXTURE.read_text() if text is None else text
        self.status = status
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        response = requests.Response()
        response.status_code = self.status
        response._content = self.text.encode()
        response.encoding = "utf-8"
        response.url = url
        return response


def live_settings():
    return load_settings({"FIRMS_MAP_KEY": "test-secret"})


def test_valid_csv_preserves_coordinates_frp_utc_and_stable_ids():
    from app.services.firms import fetch_fires

    session = FixtureSession()
    fires = fetch_fires(live_settings(), session)
    assert len(fires) == 2
    assert fires[0].latitude == 34.22
    assert fires[0].longitude == -118.55
    assert fires[0].frp_mw == 12.5
    assert fires[0].observed_at == datetime(2026, 10, 17, 0, 45, tzinfo=timezone.utc)
    assert fires[1].frp_mw is None
    assert fires[0].source == "NASA FIRMS"
    assert [f.id for f in fires] == [f.id for f in fetch_fires(live_settings(), FixtureSession())]
    assert fires[0].id != fires[1].id
    assert session.calls == [("https://firms.modaps.eosdis.nasa.gov/api/area/csv/test-secret/VIIRS_SNPP_NRT/-124.5,32.5,-114.0,42.1/1", {"timeout": (3.05, 10), "allow_redirects": False})]


def test_header_only_csv_is_successful_empty_result():
    from app.services.firms import fetch_fires
    assert fetch_fires(live_settings(), FixtureSession(HEADER)) == []


@pytest.mark.parametrize("row", [
    "91,-118,2026-10-17,0045,1", "34,-181,2026-10-17,0045,1",
    "nan,-118,2026-10-17,0045,1", "34,inf,2026-10-17,0045,1",
    ",-118,2026-10-17,0045,1", "34,-118,2026-02-30,0045,1",
    "34,-118,2026-10-17,2400,1", "34,-118,2026-10-17,noon,1",
    "34,-118,2026-10-17,0045,bad", "34,-118,2026-10-17,0045,nan",
    "34,-118,2026-10-17,0045,-1", "34,-118,2026-10-17,0045,1,extra",
])
def test_invalid_rows_are_skipped_without_inventing_zero(row):
    from app.services.firms import fetch_fires
    fires = fetch_fires(live_settings(), FixtureSession(HEADER + row + "\n34,-118,2026-10-17,0045,0\n"))
    assert len(fires) == 1
    assert fires[0].frp_mw == 0


@pytest.mark.parametrize("text", ["", "Error: invalid MAP_KEY test-secret", "<html>error</html>", "latitude,longitude\n34,-118", 'latitude,longitude,acq_date,acq_time,frp\n"unterminated'])
def test_unrecognizable_or_malformed_csv_is_sanitized_provider_failure(text):
    from app.services.firms import fetch_fires
    with pytest.raises(ProviderError) as failure:
        fetch_fires(live_settings(), FixtureSession(text))
    assert failure.value.provider == "NASA FIRMS"
    assert "test-secret" not in str(failure.value)
    assert "http" not in str(failure.value)


@pytest.mark.parametrize("status,error", [(429,None),(500,None),(302,None),(200,requests.Timeout("test-secret https://secret")),(200,requests.ConnectionError("test-secret"))])
def test_transport_and_http_failures_are_sanitized(status, error):
    from app.services.firms import fetch_fires
    session = FixtureSession(status=status, error=error)
    with pytest.raises(ProviderError) as failure:
        fetch_fires(live_settings(), session)
    assert len(session.calls) == 1
    assert "test-secret" not in str(failure.value)
    assert "https://" not in str(failure.value)


def test_sample_mode_is_deterministic_and_never_contacts_provider():
    from app.services.firms import fetch_fires
    session = FixtureSession(error=AssertionError("sample contacted provider"))
    fires = fetch_fires(load_settings({"WILDFYRE_DATA_MODE": "sample"}), session)
    assert fires[0].id == "sample-fire-1"
    assert not session.calls

def test_snapshot_retains_model_inputs_without_a_second_request():
    from app.services.firms import fetch_fire_snapshot
    session=FixtureSession()
    snapshot=fetch_fire_snapshot(live_settings(),session)
    assert len(session.calls)==1 and len(snapshot.fires)==2
    row=snapshot.observations[0]
    assert row.fire_id==snapshot.fires[0].id
    assert (row.satellite,row.confidence,row.brightness4,row.brightness5,row.frp,row.daynight,row.fire_type)==("N","n",330.4,290.1,12.5,"N",None)

def test_missing_ml_columns_preserves_public_map_fires():
    from app.services.firms import fetch_fire_snapshot
    snapshot=fetch_fire_snapshot(live_settings(),FixtureSession(HEADER+"34,-118,2026-10-17,0045,2\n"))
    assert len(snapshot.fires)==1 and snapshot.observations[0].problems

def test_bad_measurement_kept_as_incomplete_ml_contributor():
    from app.services.firms import fetch_fire_snapshot
    text=FIXTURE.read_text().replace("330.4","not-numeric").replace("12.5","bad")
    snapshot=fetch_fire_snapshot(live_settings(),FixtureSession(text))
    assert len(snapshot.fires)==1
    assert len(snapshot.observations)==2
    assert snapshot.observations[0].problems

@pytest.mark.parametrize("tail,unavailable",[("",True),(",,,",False)])
def test_short_numeric_row_is_malformed_but_explicit_blanks_can_be_imputed(tail,unavailable):
    from app.services.firms import fetch_fire_snapshot
    from app.models.features import build_cell_features
    text=("latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,bright_ti4,bright_ti5,frp\n"
          +"34.22,-118.55,2026-10-18,0700,N,n,D"+tail+"\n")
    snapshot=fetch_fire_snapshot(live_settings(),FixtureSession(text))
    cell=build_cell_features(snapshot,datetime(2026,10,18,13,5,tzinfo=timezone.utc),"VIIRS_SNPP_NRT").cells[0]
    assert (cell.reason=="incomplete_model_inputs")==unavailable
    assert cell.features["mean_frp"] is None
