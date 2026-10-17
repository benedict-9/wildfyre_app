"""Export the trusted WF08 forest and prove portable inference parity."""
import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

from verify_fire_persistence import ROOT, verify_files, verify_dataset, verify_model

sys.path.insert(0, str(ROOT / "backend"))
from app.models.fire_model import ForestModel


def verify_live_features(directory, frame):
    from collections import defaultdict
    from datetime import datetime, timedelta, timezone
    from app.services.firms import _parse_snapshot, FireSnapshot
    from app.models.features import build_cell_features

    snapshot = _parse_snapshot((directory / "firms_california_2022_2024_vegetation_fire.csv").read_text(),
                               "VIIRS_SNPP_SP")
    groups = defaultdict(list)
    for row in snapshot.observations:
        start = row.observed_at.replace(hour=(row.observed_at.hour//6)*6,minute=0,second=0,microsecond=0)
        groups[start].append(row)
    actual = {}
    for start, rows in groups.items():
        if start + timedelta(hours=30) > datetime(start.year,11,1,tzinfo=timezone.utc):
            continue
        batch = build_cell_features(FireSnapshot([],rows,snapshot.columns), start+timedelta(hours=6),
                                    "VIIRS_SNPP_SP")
        if batch.reason or any(c.reason for c in batch.cells):
            raise ValueError("Historical feature preparation unavailable")
        for cell in batch.cells:
            actual[(start.year,cell.grid_x,cell.grid_y,start)] = cell.features
    expected = {(int(row.season_year),int(row.grid_x),int(row.grid_y),row.window_start):row
                for row in frame.itertuples()}
    if actual.keys() != expected.keys():
        raise ValueError("Historical feature keys differ")
    maximum = 0.0
    for key, features in actual.items():
        for name, value in features.items():
            maximum = max(maximum, abs(value - getattr(expected[key],name)))
    if maximum > 1e-9:
        raise ValueError("Historical feature values differ")
    return {"historical_cell_windows":len(actual),"historical_feature_max_error":maximum}


def export(directory, output):
    import joblib
    import numpy as np
    import pandas as pd

    contract = json.loads((ROOT / "models/fire-persistence/model.json").read_text())
    verify_files(directory, contract["files"])
    frame = verify_dataset(directory)
    verify_model(directory, contract, frame)
    feature_parity = verify_live_features(directory, frame)
    pipeline = joblib.load(directory / "fire_persistence_random_forest.joblib")
    forest = pipeline.named_steps["classifier"]
    source_hash = contract["files"][0]["sha256"]
    trees = []
    for estimator in forest.estimators_:
        tree = estimator.tree_
        values = tree.value[:, 0, :]
        positive = values[:, 1] / values.sum(axis=1)
        trees.append({"left": tree.children_left.tolist(), "right": tree.children_right.tolist(),
                      "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(),
                      "positive": positive.tolist()})
    data = {"format": "wildfyre-rf-v1", "features": contract["features"], "classes": [0,1],
            "model_version": contract["model_version"], "source_sha256": source_hash,
            "medians": pipeline.named_steps["imputer"].statistics_.tolist(), "trees": trees}
    output.mkdir(parents=True, exist_ok=True)
    pending = output / "forest.pending.gz"
    pending.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":"), allow_nan=False).encode(),
                                      compresslevel=9, mtime=0))
    test = frame[frame.season_year.isin(contract["test_years"])][contract["features"]]
    first = test.iloc[0].to_dict()
    descriptor = {"bundled_file": "forest.json.gz", "format": data["format"], "tree_count": len(trees), "source_sha256": source_hash,
                  "bytes": pending.stat().st_size, "sha256": hashlib.sha256(pending.read_bytes()).hexdigest(),
                  "download_url": "https://github.com/benedict-9/wildfyre/releases/download/wf09-rf-portable-v1/forest.json.gz",
                  "self_check": {"features": first, "score": float(pipeline.predict_proba(test.iloc[:1])[0,1])}}
    candidate = {**contract, "serving_artifact": descriptor}
    started = time.perf_counter()
    portable = ForestModel.load(pending, candidate)
    portable.self_check()
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    scores = np.array([portable.predict(row) for row in test.to_dict("records")])
    inference_seconds = time.perf_counter() - started
    expected = pipeline.predict_proba(test)[:,1]
    error = float(np.max(np.abs(scores - expected)))
    matches = bool(np.array_equal((scores > .5).astype(int), pipeline.predict(test)))
    cases = [first.copy() for _ in range(14)]
    for i, name in enumerate(contract["features"]):
        cases[i][name] = None
    cases[-1] = dict.fromkeys(contract["features"])
    # Values immediately around several real split thresholds after float32 conversion.
    for tree in trees[:3]:
        for feature, threshold in list(zip(tree["feature"], tree["threshold"]))[:20]:
            if feature < 0:
                continue
            for value in (np.nextafter(np.float32(threshold), np.float32(-np.inf)),
                          np.float32(threshold), np.nextafter(np.float32(threshold), np.float32(np.inf))):
                case = first.copy()
                case[contract["features"][feature]] = float(value)
                cases.append(case)
    special = pd.DataFrame(cases, columns=contract["features"], dtype=float)
    special_actual = np.array([portable.predict(case) for case in cases])
    special_expected = pipeline.predict_proba(special)[:,1]
    special_error = float(np.max(np.abs(special_actual - special_expected)))
    special_matches = bool(np.array_equal((special_actual > .5).astype(int), pipeline.predict(special)))
    if len(test) != 4467 or error > 1e-12 or not matches or special_error > 1e-12 or not special_matches:
        pending.unlink()
        raise ValueError("Portable parity failed")
    report = {**feature_parity, "format": data["format"], "source_sha256": source_hash, "artifact_sha256": descriptor["sha256"],
              "artifact_bytes": descriptor["bytes"], "trees": len(trees),
              "nodes": sum(len(t["left"]) for t in trees), "held_out_rows": len(test),
              "max_probability_error": error, "identical_classes": matches,
              "missing_and_threshold_cases": len(cases), "special_max_probability_error": special_error,
              "special_identical_classes": special_matches,
              "load_self_check_seconds": load_seconds, "all_rows_inference_seconds": inference_seconds,
              "mean_prediction_ms": inference_seconds / len(test) * 1000,
              "remote_linuxone_inference_verified": False}
    pending.replace(output / "forest.json.gz")
    (output / "parity.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "serving-artifact.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    export(args.artifact_dir, args.output_dir)
