"""Small hand-computable portable forest shared by inference integration tests."""
import gzip
import hashlib
import json

def write_forest(tmp_path, change=None):
    names = ["x", "y"]
    tree = {"left": [1,-1,-1], "right": [2,-1,-1], "feature": [0,-2,-2],
            "threshold": [1.0,-2,-2], "positive": [0.5,0.2,0.8]}
    data = {"format":"wildfyre-rf-v1","features":names,"medians":[0,2],
            "classes":[0,1],"model_version":"test-v1","source_sha256":"a"*64,
            "trees":[tree, {**tree,"positive":[0.5,0.4,0.6]}]}
    if change:
        change(data)
    path=tmp_path/"forest.json.gz"
    path.write_bytes(gzip.compress(json.dumps(data).encode(),mtime=0))
    descriptor={"format":"wildfyre-rf-v1","tree_count":2,"source_sha256":"a"*64,
                "bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                "download_url":"https://example.org/forest.json.gz",
                "self_check":{"features":{"x":0,"y":2},"score":0.3}}
    contract={"features":names,"model_version":"test-v1","serving_artifact":descriptor}
    return path,contract
