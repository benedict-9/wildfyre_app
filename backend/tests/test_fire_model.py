import copy
import gzip
import json
import math
import pytest
from model_fixture import write_forest
from app.models.fire_model import ForestModel

@pytest.fixture
def forest_artifact(tmp_path):
    return write_forest(tmp_path)

@pytest.mark.parametrize("x,want",[(0,0.3),(1,0.3),(1.00000001,0.3),(1.0000002,0.7),(None,0.3)])
def test_boundary_float32_and_median(forest_artifact,x,want):
    model=ForestModel.load(*forest_artifact)
    assert model.predict({"y":2,"x":x}) == pytest.approx(want)
    assert model.feature_names == ("x","y")
    assert model.model_version == "test-v1"
    model.self_check()

@pytest.mark.parametrize("value",[True,"1",math.nan,math.inf,-math.inf,1e100])
def test_invalid_input_never_becomes_a_score(forest_artifact,value):
    with pytest.raises(ValueError):
        ForestModel.load(*forest_artifact).predict({"x":value,"y":2})

def test_predictor_rejects_missing_feature(forest_artifact):
    with pytest.raises(ValueError,match="feature"):
        ForestModel.load(*forest_artifact).predict({})

@pytest.mark.parametrize("change",[
    lambda d:d.update(format="other"),
    lambda d:d.update(model_version="other"),
    lambda d:d.update(features=["y","x"]),
    lambda d:d.update(classes=[1,0]),
    lambda d:d.update(medians=[float("nan"),2]),
    lambda d:d["trees"][0]["left"].__setitem__(0,0),
    lambda d:d["trees"][0]["right"].__setitem__(0,9),
    lambda d:d["trees"][0]["left"].__setitem__(1,2),
    lambda d:d["trees"][0]["feature"].__setitem__(0,2),
    lambda d:d["trees"][0]["positive"].__setitem__(1,2),
    lambda d:d["trees"][0]["threshold"].__setitem__(0,float("inf")),
    lambda d:d["trees"][0]["left"].append(-1),
])
def test_invalid_forest_rejected_even_with_matching_file_digest(tmp_path,change):
    with pytest.raises(ValueError):
        ForestModel.load(*write_forest(tmp_path,change))

def test_decompression_limit(tmp_path,monkeypatch):
    from app.models import fire_model
    path,contract=write_forest(tmp_path)
    monkeypatch.setattr(fire_model,"MAX_DECOMPRESSED_BYTES",10)
    with pytest.raises(ValueError):
        ForestModel.load(path,contract)

def test_self_check_mismatch_is_visible(forest_artifact):
    path,contract=forest_artifact
    contract["serving_artifact"]["self_check"]["score"]=0.9
    with pytest.raises(ValueError,match="self.check"):
        ForestModel.load(path,contract).self_check()
