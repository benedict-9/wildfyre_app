"""Explicit validated process configuration; environment files are not auto-loaded."""
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Literal, Mapping
from urllib.parse import urlsplit

BoundingBox = tuple[float, float, float, float]
DataMode = Literal["live", "sample"]
REQUEST_TIMEOUT = (3.05, 10)
GBIF_PAGE_SIZE = 100
GBIF_MAX_PAGES = 3
DEFAULT_BBOX: BoundingBox = (-124.5, 32.5, -114.0, 42.1)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORIGINS = ("http://127.0.0.1:8080", "http://localhost:8080")


@dataclass(frozen=True)
class Settings:
    data_mode: DataMode = "live"
    bbox: BoundingBox = DEFAULT_BBOX
    firms_map_key: str | None = field(default=None, repr=False)
    firms_source: str = "VIIRS_SNPP_NRT"
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS

    model_contract_path: Path = ROOT / "models/fire-persistence/model.json"
    model_artifact_path: Path = ROOT / "artifacts/fire-persistence/forest.json.gz"
    require_model: bool = False

    def __post_init__(self):
        if self.data_mode not in ("live", "sample"):
            raise ValueError("WILDFYRE_DATA_MODE must be live or sample")
        if self.firms_map_key is not None and (not isinstance(self.firms_map_key, str) or not self.firms_map_key.strip()):
            raise ValueError("FIRMS_MAP_KEY must be a nonempty string when supplied")
        if self.data_mode == "live" and not self.firms_map_key:
            raise ValueError("FIRMS_MAP_KEY is required in live mode")
        try:
            west, south, east, north = self.bbox
            valid = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in self.bbox)
            valid = valid and -180 <= west < east <= 180 and -90 <= south < north <= 90
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("WILDFYRE_BBOX must contain valid west,south,east,north bounds")
        if not isinstance(self.firms_source, str) or not re.fullmatch(r"[A-Za-z0-9_]+", self.firms_source):
            raise ValueError("FIRMS_SOURCE must be a source identifier")
        if not self.allowed_origins:
            raise ValueError("WILDFYRE_ALLOWED_ORIGINS must list explicit HTTP origins")
        for origin in self.allowed_origins:
            try:
                parsed = urlsplit(origin)
                valid_origin = parsed.scheme in ("http", "https") and parsed.hostname and parsed.port != 0
                valid_origin = valid_origin and not (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment)
            except ValueError:
                valid_origin = False
            if not valid_origin:
                raise ValueError("WILDFYRE_ALLOWED_ORIGINS must list explicit HTTP origins")


def load_settings(environ: Mapping[str, str]) -> Settings:
    raw_bbox = environ.get("WILDFYRE_BBOX")
    try:
        bbox = tuple(float(v.strip()) for v in raw_bbox.split(",")) if raw_bbox is not None else DEFAULT_BBOX
    except ValueError:
        raise ValueError("WILDFYRE_BBOX must contain four numbers") from None
    return Settings(
        model_contract_path=Path(environ.get("WILDFYRE_MODEL_CONTRACT", str(ROOT / "models/fire-persistence/model.json"))),
        model_artifact_path=Path(environ.get("WILDFYRE_MODEL_ARTIFACT", str(ROOT / "artifacts/fire-persistence/forest.json.gz"))),
        require_model=environ.get("WILDFYRE_REQUIRE_MODEL", "0") == "1",
        data_mode=environ.get("WILDFYRE_DATA_MODE", "live").strip(),
        bbox=bbox,
        firms_map_key=environ.get("FIRMS_MAP_KEY", "").strip() or None,
        firms_source=environ.get("FIRMS_SOURCE", "VIIRS_SNPP_NRT").strip(),
        allowed_origins=tuple(v.strip() for v in environ.get("WILDFYRE_ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",") if v.strip()),
    )
