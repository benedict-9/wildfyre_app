import json
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from model_fixture import write_forest
from test_firms import FixtureSession
from app.config import Settings
from app.main import create_app,get_session,get_fetched_at,get_clock
from app.models.fire_model import ForestModel

FEATURES=json.loads((Path(__file__).parents[2]/"models/fire-persistence/model.json").read_text())["features"]
NOW=datetime(2026,10,18,13,5,tzinfo=timezone.utc)
CSV="latitude,longitude,acq_date,acq_time,frp,bright_ti4,bright_ti5,satellite,confidence,daynight\n34.22,-118.55,2026-10-18,0700,10,330,290,N,n,D\n"

def configured(tmp_path,**changes):
    path,c=write_forest(tmp_path,lambda d:d.update(features=FEATURES,medians=[0]*13))
    c["features"]=FEATURES
    c["serving_artifact"]["self_check"]["features"]=dict.fromkeys(FEATURES,0)
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    return Settings(data_mode="sample",model_contract_path=contract,model_artifact_path=path,**changes)

def test_sample_load_once_real_predictions_and_separate_priorities(tmp_path,monkeypatch):
    settings=configured(tmp_path)
    original=ForestModel.load.__func__;loads=[]
    def load(cls,*args): loads.append(1);return original(cls,*args)
    monkeypatch.setattr(ForestModel,"load",classmethod(load))
    app=create_app(settings)
    app.dependency_overrides[get_session]=lambda: FixtureSession(error=AssertionError("provider"))
    with TestClient(app) as client:
        a=client.get("/risk").json();b=client.get("/risk").json()
        assert client.get("/model/status").json()=={"status":"ready","reason":None,"model_version":"test-v1","self_check":"passed"}
    assert len(loads)==1
    assert a["fire_persistence"]==b["fire_persistence"]
    report=a["fire_persistence"]
    assert report["status"]=="ready" and report["mode"]=="sample"
    assert report["window_start"]=="2026-10-17T00:00:00Z" and report["window_end"]=="2026-10-17T06:00:00Z"
    assert report["cells"][0]["score"]==pytest.approx(.3)
    assert all(z["priority"]=="UNASSESSED" and z["risk_method"]=="proximity" for z in a["wildlife_zones"])

@pytest.mark.parametrize("csv,source,status,reason",[
    (CSV,"VIIRS_SNPP_NRT","ready",None),
    (CSV.splitlines()[0]+"\n","VIIRS_SNPP_NRT","empty",None),
    (CSV.replace(",n,D",",,D"),"VIIRS_SNPP_NRT","unavailable","no_scorable_cells"),
    (CSV,"MODIS_NRT","unavailable","unsupported_source"),
])
def test_live_uses_one_firms_request_and_current_window(tmp_path,monkeypatch,csv,source,status,reason):
    import app.main as routes
    settings=replace(configured(tmp_path),data_mode="live",firms_map_key="test-secret",firms_source=source)
    session=FixtureSession(csv)
    monkeypatch.setattr(routes,"fetch_occurrences",lambda *args:([],False))
    app=create_app(settings)
    app.dependency_overrides[get_session]=lambda:session
    app.dependency_overrides[get_clock]=lambda:lambda:NOW
    with TestClient(app) as client:
        response=client.get("/risk")
    assert response.status_code==200
    report=response.json()["fire_persistence"]
    assert len(session.calls)==1 and report["status"]==status and report["reason"]==reason
    assert report["window_start"]=="2026-10-18T06:00:00Z"
    assert report["horizon_end"]=="2026-10-19T12:00:00Z"
    if status=="ready":
        assert report["experimental"] is True
        assert "vegetation_type_unavailable" in report["quality_flags"]
        assert report["cells"][0]["score"]==pytest.approx(.3)
    if reason=="no_scorable_cells":
        assert report["cells"][0]["score"] is None
        assert report["cells"][0]["reason"]=="incomplete_model_inputs"

@pytest.mark.parametrize("failure",["missing","corrupt","self-check"])
def test_model_failure_keeps_rules_and_sanitizes_readiness(tmp_path,failure):
    settings=configured(tmp_path)
    if failure=="missing": settings.model_artifact_path.unlink()
    elif failure=="corrupt": settings.model_artifact_path.write_bytes(b"bad")
    else:
        c=json.loads(settings.model_contract_path.read_text())
        c["serving_artifact"]["self_check"]["score"]=.99
        settings.model_contract_path.write_text(json.dumps(c))
    with TestClient(create_app(settings)) as client:
        response=client.get("/risk")
        status=client.get("/model/status")
        assert status.json()["status"]=="unavailable"
        assert str(tmp_path) not in status.text
    assert response.status_code==200
    assert response.json()["fire_persistence"]["status"]=="unavailable"
    assert response.json()["wildlife_zones"]
    with pytest.raises(ValueError,match="Required model"):
        with TestClient(create_app(replace(settings,require_model=True))): pass

def test_single_process_routes_and_static_files(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        assert client.get("/").json()=={"project":"WildFyre","status":"running"}
        for path in ("/app/","/app/app.js","/app/config.js","/app/styles.css","/app/favicon.svg"):
            assert client.get(path).status_code==200

def test_cell_never_turns_missing_or_invalid_score_into_zero():
    from app.schemas import PersistenceCell
    values=dict(id="0:0",grid_x=0,grid_y=0,latitude=34.,longitude=-118.,fire_ids=["f"],fire_count=1)
    for score,reason in ((float("nan"),None),(1.1,None),(None,None),(.5,"invalid")):
        with pytest.raises(ValueError): PersistenceCell(**values,score=score,reason=reason)

@pytest.mark.parametrize("before,after,observed,window_end",[
 ("2026-10-18T11:59:59+00:00","2026-10-18T12:00:01+00:00","2026-10-18,0700","2026-10-18T12:00:00Z"),
 ("2026-10-18T23:59:59+00:00","2026-10-19T00:00:01+00:00","2026-10-18,1900","2026-10-19T00:00:00Z")
])
def test_retrieval_crossing_boundary_uses_completed_snapshot_time(tmp_path,monkeypatch,before,after,observed,window_end):
    import app.main as routes
    current=[datetime.fromisoformat(before)]
    clock=lambda:current[0]
    class AdvancingSession(FixtureSession):
        def get(self,*args,**kwargs):
            response=super().get(*args,**kwargs)
            current[0]=datetime.fromisoformat(after)
            return response
    settings=replace(configured(tmp_path),data_mode="live",firms_map_key="test-secret")
    session=AdvancingSession(CSV.replace("2026-10-18,0700",observed))
    monkeypatch.setattr(routes,"fetch_occurrences",lambda *a:([],False))
    app=create_app(settings)
    app.dependency_overrides[get_session]=lambda:session
    app.dependency_overrides[get_clock]=lambda:clock
    with TestClient(app) as client: data=client.get("/risk").json()
    assert data["fetched_at"]==after.replace("+00:00","Z")
    assert data["fire_persistence"]["window_end"]==window_end
    assert data["fire_persistence"]["status"]=="ready"
