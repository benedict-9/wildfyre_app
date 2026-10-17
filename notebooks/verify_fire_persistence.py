"""Verify the accepted fire-persistence artifact and data without retraining."""
import argparse
import ast
import hashlib
import json
import platform
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score,
)


ROOT = Path(__file__).resolve().parents[1]


def verify_files(directory, files):
    for item in files:
        path = directory / item["name"]
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if path.stat().st_size != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError(f"Artifact integrity mismatch: {item['name']}")
    print("PASS: the three required artifacts match model.json.")


def notebook_helpers():
    notebook = json.loads((ROOT / "notebooks/fire_persistence.ipynb").read_text(encoding="utf-8"))
    names = {"clean_firms_data", "add_grid_and_time_window", "aggregate_fire_windows",
             "add_persistence_target", "censor_incomplete_horizons"}
    namespace = {
        "pd": pd, "np": np, "WEST": -124.5, "SOUTH": 32.5,
        "EAST": -114.0, "NORTH": 42.1, "GRID_SIZE_KM": 5.0,
        "OBSERVATION_WINDOW_HOURS": 6, "PREDICTION_HORIZON_HOURS": 24,
        "KM_PER_DEG_LAT": 111.32,
        "KM_PER_DEG_LON": 111.32 * np.cos(np.deg2rad(37.3)),
    }
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                code = ast.Module(body=[node], type_ignores=[])
                exec(compile(code, "<notebook helper>", "exec"), namespace)
    if not names.issubset(namespace):
        raise ValueError("Canonical notebook is missing required preparation helpers.")
    return namespace


def verify_dataset(directory):
    helpers = notebook_helpers()
    source = pd.read_csv(directory / "firms_california_2022_2024_vegetation_fire.csv")
    fires = helpers["clean_firms_data"](source)
    if len(fires) != len(source):
        raise ValueError("Combined source contains invalid or duplicate detections.")
    if not fires["confidence"].isin(["n", "h"]).all() or not (fires["type"] == 0).all():
        raise ValueError("Combined source contains nonqualifying detections.")
    if not (fires["season_year"] == fires["observed_at"].dt.year).all():
        raise ValueError("Season year disagrees with observation timestamp.")
    gridded = helpers["add_grid_and_time_window"](fires)
    windows = helpers["aggregate_fire_windows"](gridded)
    ends = {year: pd.Timestamp(f"{year}-11-01", tz="UTC") for year in (2022, 2023, 2024)}
    rebuilt = helpers["censor_incomplete_horizons"](
        helpers["add_persistence_target"](windows), ends,
    )
    supplied = pd.read_csv(directory / "fire_persistence_windows_2022_2024.csv")
    for column in ("window_start", "prediction_at", "horizon_end", "season_observation_end"):
        supplied[column] = pd.to_datetime(supplied[column], utc=True)
    keys = ["season_year", "grid_x", "grid_y", "window_start"]
    expected = rebuilt.sort_values(keys).reset_index(drop=True)
    actual = supplied.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        expected[actual.columns], actual, check_dtype=False, check_exact=False,
        atol=1e-9, rtol=1e-9,
    )
    print(f"PASS: {len(fires):,} detections reproduce all {len(actual):,} modelling rows.")
    return supplied


def verify_model(directory, contract, frame):
    features = contract["features"]
    runtime = contract["runtime"]
    if sklearn.__version__ != runtime["scikit_learn"] or joblib.__version__ != runtime["joblib"]:
        raise ValueError("Use the pinned artifact-compatible verification dependencies.")
    path = directory / "fire_persistence_random_forest.joblib"
    with warnings.catch_warnings():
        warnings.simplefilter("error", sklearn.exceptions.InconsistentVersionWarning)
        model = joblib.load(path)
    if list(model.named_steps) != ["imputer", "classifier"]:
        raise ValueError("Unexpected model pipeline.")
    classifier = model.named_steps["classifier"]
    if list(model.feature_names_in_) != features or model.n_features_in_ != len(features):
        raise ValueError("Model feature order disagrees with model.json.")
    if list(classifier.classes_) != [0, 1]:
        raise ValueError("Unexpected model classes.")
    if (classifier.n_estimators, classifier.random_state, classifier.class_weight) != (300, 42, "balanced"):
        raise ValueError("Unexpected Random Forest configuration.")
    train = frame[frame.season_year.isin(contract["training_years"])]
    test = frame[frame.season_year.isin(contract["test_years"])]
    if len(train) != contract["training_samples"] or len(test) != contract["test_samples"]:
        raise ValueError("Dataset split disagrees with model.json.")
    inputs, target = test[features], test.target_persists_24h
    predictions = model.predict(inputs)
    probabilities = model.predict_proba(inputs)[:, 1]
    if not np.isfinite(probabilities).all() or not ((probabilities >= 0) & (probabilities <= 1)).all():
        raise ValueError("Model returned invalid probabilities.")
    metrics = {
        "accuracy": float(accuracy_score(target, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(target, predictions)),
        "precision": float(precision_score(target, predictions, zero_division=0)),
        "recall": float(recall_score(target, predictions, zero_division=0)),
        "f1": float(f1_score(target, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(target, probabilities)),
    }
    for name, expected in contract["evaluation"].items():
        if abs(metrics[name] - expected) > 1e-12:
            raise ValueError(f"Evaluation mismatch: {name}")
    reloaded = joblib.load(path)
    if not np.array_equal(predictions, reloaded.predict(inputs)) or not np.array_equal(
        probabilities, reloaded.predict_proba(inputs)[:, 1],
    ):
        raise ValueError("Reload changed model predictions or probabilities.")
    return {
        "runtime": {
            "architecture": platform.machine(), "python": platform.python_version(),
            "sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__,
            "scipy": scipy.__version__, "joblib": joblib.__version__,
        },
        "model_sha256": next(item["sha256"] for item in contract["files"] if item["name"] == path.name),
        "train_samples": len(train), "test_samples": len(test), "metrics": metrics,
        "confusion_matrix": confusion_matrix(target, predictions).tolist(),
        "majority_baseline_accuracy": float((target == 0).mean()),
        "feature_order_verified": True,
        "reload_predictions_and_probabilities_match": True,
        "remote_linuxone_inference_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    contract = json.loads((ROOT / "models/fire-persistence/model.json").read_text(encoding="utf-8"))
    verify_files(args.artifact_dir, contract["files"])
    frame = verify_dataset(args.artifact_dir)
    report = verify_model(args.artifact_dir, contract, frame)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
