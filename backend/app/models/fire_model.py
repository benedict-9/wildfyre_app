"""Validated standard-library scorer for exported RandomForestClassifier trees."""
import gzip
import json
import math
import struct
from pathlib import Path
from collections.abc import Mapping

from .artifacts import verify_artifact

MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_NODES = 2_000_000


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


class ForestModel:
    def __init__(self, data, descriptor):
        self.model_version = data["model_version"]
        self.feature_names = tuple(data["features"])
        self._medians = data["medians"]
        self._trees = data["trees"]
        self._check = descriptor["self_check"]

    @classmethod
    def load(cls, path: Path, contract: dict):
        descriptor = contract["serving_artifact"]
        verify_artifact(path, descriptor)
        try:
            with gzip.open(path, "rb") as stream:
                payload = stream.read(MAX_DECOMPRESSED_BYTES + 1)
            if len(payload) > MAX_DECOMPRESSED_BYTES:
                raise ValueError("Decompressed artifact exceeds limit")
            data = json.loads(payload)
            cls._validate(data, contract)
            return cls(data, descriptor)
        except (OSError, EOFError, KeyError, TypeError, json.JSONDecodeError, RecursionError):
            raise ValueError("Invalid portable forest") from None

    @staticmethod
    def _validate(data, contract):
        descriptor = contract["serving_artifact"]
        names = contract["features"]
        if (descriptor["format"] != "wildfyre-rf-v1" or data["format"] != descriptor["format"]
                or not names or len(names) > 128 or len(set(names)) != len(names)
                or not all(isinstance(name, str) and name for name in names)
                or data["features"] != names or data["classes"] != [0, 1]
                or data["model_version"] != contract["model_version"]
                or data["source_sha256"] != descriptor["source_sha256"]):
            raise ValueError("Forest contract mismatch")
        medians, trees = data["medians"], data["trees"]
        if len(medians) != len(names) or not all(finite_number(v) for v in medians):
            raise ValueError("Invalid imputer")
        if (type(descriptor["tree_count"]) is not int or not isinstance(trees, list)
                or not 1 <= len(trees) <= 300 or len(trees) != descriptor["tree_count"]):
            raise ValueError("Invalid tree count")
        nodes = 0
        for tree in trees:
            arrays = [tree[key] for key in ("left", "right", "feature", "threshold", "positive")]
            count = len(arrays[0])
            nodes += count
            if not count or nodes > MAX_NODES or not all(isinstance(a, list) and len(a) == count for a in arrays):
                raise ValueError("Invalid tree arrays")
            left, right, features, thresholds, positive = arrays
            for i in range(count):
                if not all(type(v) is int for v in (left[i], right[i], features[i])):
                    raise ValueError("Invalid tree indexes")
                if not finite_number(thresholds[i]) or not finite_number(positive[i]) or not 0 <= positive[i] <= 1:
                    raise ValueError("Invalid tree output")
                if left[i] == right[i] == -1:
                    continue
                if not (i < left[i] < count and i < right[i] < count and 0 <= features[i] < len(names)):
                    raise ValueError("Invalid tree children or feature")

    def predict(self, features: Mapping[str, float | None]) -> float:
        values = []
        for name, median in zip(self.feature_names, self._medians):
            if name not in features:
                raise ValueError("Missing feature")
            value = median if features[name] is None else features[name]
            if not finite_number(value):
                raise ValueError("Invalid feature")
            try:
                value = struct.unpack("<f", struct.pack("<f", value))[0]
            except (OverflowError, struct.error):
                raise ValueError("Invalid feature range") from None
            if not math.isfinite(value):
                raise ValueError("Invalid feature range")
            values.append(value)
        total = 0.0
        for tree in self._trees:
            i = 0
            while tree["left"][i] != -1:
                i = tree["left"][i] if values[tree["feature"][i]] <= tree["threshold"][i] else tree["right"][i]
            total += tree["positive"][i]
        score = total / len(self._trees)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid model score")
        return score

    def self_check(self):
        expected = self._check.get("score")
        if not finite_number(expected) or abs(self.predict(self._check["features"]) - expected) > 1e-12:
            raise ValueError("Model self-check failed")
