"""Offline regressions execute notebook helper definitions, never downloads/training.

Run with a Python environment containing pandas and numpy:
    python -m unittest discover -s notebooks/tests -v
"""
import ast
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


NOTEBOOK = Path(__file__).resolve().parents[1] / "fire_persistence.ipynb"


def helper(name, **extra):
    namespace = {"pd": pd, "np": np, "PREDICTION_HORIZON_HOURS": 24,
                 "OBSERVATION_WINDOW_HOURS": 6}
    namespace.update(extra)
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
                return namespace[name]
    raise AssertionError(f"Missing notebook helper: {name}")


def windows(times, unit="us", cells=None, years=None):
    count = len(times)
    return pd.DataFrame({
        "season_year": years or [2024] * count,
        "grid_x": cells or [0] * count,
        "grid_y": [0] * count,
        "window_start": pd.to_datetime(times, utc=True, format="mixed").as_unit(unit),
    })


class PersistenceTests(unittest.TestCase):
    def test_malformed_time_and_infinite_frp_are_rejected(self):
        clean = helper("clean_firms_data", WEST=-124.5, SOUTH=32.5, EAST=-114.0, NORTH=42.1)
        raw = pd.DataFrame({"latitude": [34.] * 4, "longitude": [-118.] * 4,
                            "acq_date": ["2024-06-01"] * 4,
                            "acq_time": ["0834", "-100", "0834junk", "0900"],
                            "satellite": ["N"] * 4, "confidence": ["n"] * 4,
                            "frp": [1., 1., 1., float("inf")]})
        result = clean(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.observed_at.iloc[0].hour, 8)

    def test_aggregation_uses_only_the_current_window(self):
        raw = pd.DataFrame({
            "season_year": [2024] * 3,
            "grid_x": [0] * 3, "grid_y": [0] * 3,
            "window_start": pd.to_datetime(["2024-06-01T00:00:00Z"] * 2 + ["2024-06-01T06:00:00Z"]),
            "observed_at": pd.to_datetime(["2024-06-01T00:10:00Z", "2024-06-01T05:50:00Z", "2024-06-01T06:30:00Z"]),
            "latitude": [34.] * 3, "longitude": [-118.] * 3,
            "confidence": ["n", "h", "h"], "daynight": ["N", "D", "D"],
            "frp": [2., 4., 1000.], "bright_ti4": [300., 320., 999.],
            "bright_ti5": [280., 290., 999.],
        })
        result = helper("aggregate_fire_windows")(raw)
        self.assertEqual(result.fire_count.tolist(), [2, 1])
        self.assertEqual(result.mean_frp.tolist(), [3., 1000.])
        self.assertEqual(result.high_confidence_count.tolist(), [1, 1])
        self.assertEqual(result.night_detection_count.tolist(), [1, 0])
        self.assertEqual(helper("add_persistence_target")(result).target_persists_24h.tolist(), [1, 0])

    def test_training_only_cells_skip_without_a_model(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        for index in (69, 70, 71, 78):
            with self.subTest(cell=index):
                exec(compile("".join(notebook["cells"][index]["source"]), str(NOTEBOOK), "exec"), {"TRAIN_MODEL": False})

    def test_all_missing_training_feature_fails_before_imputation(self):
        frame = pd.DataFrame({"fire_count": [1, 2], "mean_frp": [np.nan, np.nan]})
        with self.assertRaisesRegex(ValueError, "mean_frp"):
            helper("validate_training_features")(frame, ["fire_count", "mean_frp"])
        frame.loc[0, "mean_frp"] = 2.0
        helper("validate_training_features")(frame, ["fire_count", "mean_frp"])

    def test_detection_72_hours_later_is_not_24_hour_persistence(self):
        for unit in ("us", "ns"):
            with self.subTest(unit=unit):
                data = windows(["2024-06-01", "2024-06-04"], unit)
                result = helper("add_persistence_target")(data)
                self.assertEqual(result.target_persists_24h.tolist(), [0, 0])

    def test_four_future_bins_are_included_but_fifth_is_not(self):
        for hours, expected in ((6, 1), (24, 1), (30, 0)):
            with self.subTest(hours=hours):
                start = pd.Timestamp("2024-06-01", tz="UTC")
                data = windows([start, start + pd.Timedelta(hours=hours)])
                self.assertEqual(helper("add_persistence_target")(data).target_persists_24h.iloc[0], expected)

    def test_cells_and_seasons_do_not_share_targets(self):
        data = windows(["2024-06-01", "2024-06-01T06:00:00"], cells=[0, 1])
        self.assertEqual(helper("add_persistence_target")(data).target_persists_24h.tolist(), [0, 0])
        data = windows(["2023-10-31T18:00:00", "2024-06-01"], years=[2023, 2024])
        self.assertEqual(helper("add_persistence_target")(data).target_persists_24h.tolist(), [0, 0])

    def test_complete_future_coverage_is_measured_from_window_end(self):
        data = windows(["2024-10-30T18:00:00", "2024-10-31T00:00:00"])
        result = helper("censor_incomplete_horizons")(data, {2024: pd.Timestamp("2024-11-01", tz="UTC")})
        self.assertEqual(len(result), 1)
        self.assertEqual(result.prediction_at.iloc[0], pd.Timestamp("2024-10-31", tz="UTC"))
        self.assertEqual(result.horizon_end.iloc[0], pd.Timestamp("2024-11-01", tz="UTC"))

    def test_unknown_season_coverage_fails_instead_of_labelling_negative(self):
        with self.assertRaisesRegex(ValueError, "coverage"):
            helper("censor_incomplete_horizons")(windows(["2024-06-01"]), {})


if __name__ == "__main__":
    unittest.main()
