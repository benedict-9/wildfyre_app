"""Pure current-window features matching the accepted notebook's fixed grid."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.firms import FireSnapshot

WEST, SOUTH, EAST, NORTH = -124.5, 32.5, -114.0, 42.1
KM_LAT = 111.32
KM_LON = KM_LAT * math.cos(math.radians(37.3))
MODEL_COLUMNS = frozenset(("satellite","confidence","bright_ti4","bright_ti5","frp","daynight"))
SAMPLE_CLOCK = datetime(2026,10,17,6,tzinfo=timezone.utc)


@dataclass(frozen=True)
class ModelObservation:
    fire_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    satellite: str
    confidence: str
    brightness4: float | None
    brightness5: float | None
    frp: float | None
    daynight: str
    fire_type: int | None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class CellInput:
    id: str
    grid_x: int
    grid_y: int
    latitude: float
    longitude: float
    fire_ids: tuple[str, ...]
    fire_count: int
    features: dict[str, float | None]
    reason: str | None = None


@dataclass(frozen=True)
class FeatureBatch:
    window_start: datetime
    window_end: datetime
    horizon_end: datetime
    cells: tuple[CellInput, ...]
    quality_flags: tuple[str, ...] = ()
    reason: str | None = None


def build_cell_features(snapshot: "FireSnapshot", fetched_at: datetime, source: str) -> FeatureBatch:
    fetched_at = fetched_at.astimezone(timezone.utc)
    end = fetched_at.replace(hour=(fetched_at.hour // 6)*6, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=6)
    flags = ("nrt_transfer_unvalidated",) if source == "VIIRS_SNPP_NRT" else ()
    if "type" not in snapshot.columns:
        flags += ("vegetation_type_unavailable",)
    def result(cells=(), reason=None):
        return FeatureBatch(start, end, end+timedelta(hours=24), tuple(cells), flags, reason)
    if source not in ("VIIRS_SNPP_NRT", "VIIRS_SNPP_SP"):
        return result(reason="unsupported_source")
    if not MODEL_COLUMNS.issubset(snapshot.columns):
        return result(reason="missing_model_columns")
    if snapshot.problems:
        return result(reason="unlocated_observations")
    groups, seen, damaged = {}, set(), set()
    for row in snapshot.observations:
        if not (start <= row.observed_at < end and WEST <= row.longitude <= EAST and SOUTH <= row.latitude <= NORTH):
            continue
        if row.confidence == "l" or (row.fire_type is not None and row.fire_type != 0):
            continue
        x = math.floor((row.longitude-WEST)*KM_LON/5)
        y = math.floor((row.latitude-SOUTH)*KM_LAT/5)
        cell = (x,y)
        if row.problems or row.confidence not in ("n","h") or row.daynight not in ("D","N") or not row.satellite:
            damaged.add(cell)
        identity = (row.satellite,row.latitude,row.longitude,row.observed_at)
        if identity in seen:
            continue
        seen.add(identity)
        groups.setdefault(cell, []).append(row)
    cells = []
    for (x,y), rows in sorted(groups.items()):
        features = {"fire_count": len(rows)}
        for field, name in (("frp","frp"),("brightness4","bright_ti4"),("brightness5","bright_ti5")):
            values = [getattr(row,field) for row in rows if getattr(row,field) is not None]
            features["mean_"+name] = sum(values)/len(values) if values else None
            features["max_"+name] = max(values) if values else None
        features.update(high_confidence_count=sum(r.confidence=="h" for r in rows),
                        normal_confidence_count=sum(r.confidence=="n" for r in rows),
                        day_detection_count=sum(r.daynight=="D" for r in rows),
                        night_detection_count=sum(r.daynight=="N" for r in rows),
                        month=start.month, hour_utc=start.hour)
        cells.append(CellInput(f"{x}:{y}", x, y, SOUTH+(y+.5)*5/KM_LAT, WEST+(x+.5)*5/KM_LON,
                               tuple(dict.fromkeys(r.fire_id for r in rows)), len(rows), features,
                               "incomplete_model_inputs" if (x,y) in damaged else None))
    return result(cells)
