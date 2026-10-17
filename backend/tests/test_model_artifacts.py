import json
import pytest
import requests
from model_fixture import write_forest
from app.models.artifacts import prepare_artifact,verify_artifact

class Transport:
    def __init__(self,body=None,error=False): self.body,self.error,self.calls=body,error,0
    def get(self,url,**kwargs):
        self.calls+=1
        if self.error: raise requests.Timeout("SECRET")
        class Response:
            status_code=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def iter_content(inner,chunk_size):
                yield self.body
        return Response()

def test_integrity_size_and_hash(tmp_path):
    path,c=write_forest(tmp_path)
    verify_artifact(path,c["serving_artifact"])
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError): verify_artifact(path,c["serving_artifact"])

def test_atomic_download_and_verified_cache_no_network(tmp_path):
    path,c=write_forest(tmp_path); body=path.read_bytes()
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    transport=Transport(body)
    cached=prepare_artifact(contract,tmp_path/"cache",transport)
    assert cached.read_bytes()==body
    assert prepare_artifact(contract,tmp_path/"cache",Transport(error=True))==cached

@pytest.mark.parametrize("failure",["timeout","hash","oversize"])
def test_failed_preparation_retains_old_cache_and_sanitizes(tmp_path,failure):
    path,c=write_forest(tmp_path)
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    cache=tmp_path/"cache";cache.mkdir()
    old=cache/"forest.json.gz";old.write_bytes(b"old")
    transport=Transport(b"x"*(c["serving_artifact"]["bytes"]+1) if failure=="oversize" else b"bad",
                        error=failure=="timeout")
    with pytest.raises(ValueError) as err: prepare_artifact(contract,cache,transport)
    assert "SECRET" not in str(err.value)
    assert old.read_bytes()==b"old"
    assert not list(cache.glob("*.tmp"))

def test_bundled_forest_prepares_atomic_cache_without_private_release_access(tmp_path):
    path,c=write_forest(tmp_path)
    c["serving_artifact"]["bundled_file"]="forest.json.gz"
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    body=path.read_bytes()
    transport=Transport(error=True)
    cached=prepare_artifact(contract,tmp_path/"cache",transport)
    assert cached.read_bytes()==body
    assert transport.calls==0
    path.unlink()
    assert prepare_artifact(contract,tmp_path/"cache",transport)==cached

@pytest.mark.parametrize("missing",[False,True])
def test_invalid_required_bundle_fails_without_network_and_preserves_cache(tmp_path,missing):
    path,c=write_forest(tmp_path)
    c["serving_artifact"]["bundled_file"]="forest.json.gz"
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    if missing:path.unlink()
    else:path.write_bytes(b"bad bundle")
    cache=tmp_path/"cache";cache.mkdir();old=cache/"forest.json.gz";old.write_bytes(b"old")
    transport=Transport(error=True)
    with pytest.raises(ValueError,match="Bundled"):
        prepare_artifact(contract,cache,transport)
    assert transport.calls==0 and old.read_bytes()==b"old"
