"""NASA FIRMS area CSV normalization (no automatic sample fallback)."""
import csv
from dataclasses import dataclass
import math
from datetime import datetime, timezone
import hashlib
from io import StringIO
import re
from urllib.parse import quote

from pydantic import ValidationError
import requests

from app.config import REQUEST_TIMEOUT, Settings
from app.data import sample_fire_events
from app.models.features import ModelObservation, MODEL_COLUMNS
from app.schemas import FireEvent
from app.services.errors import ProviderError

PROVIDER = "NASA FIRMS"
REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date", "acq_time"}


@dataclass(frozen=True)
class FireSnapshot:
    fires: list[FireEvent]
    observations: list[ModelObservation]
    columns: frozenset[str]
    problems: tuple[str, ...] = ()


def fetch_fires(settings: Settings, session: requests.Session) -> list[FireEvent]:
    return fetch_fire_snapshot(settings, session).fires


def fetch_fire_snapshot(settings: Settings, session: requests.Session) -> FireSnapshot:
    if settings.data_mode == "sample":
        fires = [FireEvent.model_validate(row) for row in sample_fire_events]
        # Explicit synthetic inputs, not measurements inferred from public fields.
        observations = [ModelObservation(fires[0].id,34.22,-118.55,
                        datetime(2026,10,17,4,tzinfo=timezone.utc),
                        "N","n",330.4,290.1,12.5,"N",0)]
        return FireSnapshot(fires, observations, MODEL_COLUMNS | REQUIRED_COLUMNS | {"type"})

    bounds = ",".join(str(v) for v in settings.bbox)
    key = quote(settings.firms_map_key, safe="")
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{settings.firms_source}/{bounds}/1"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise ProviderError(PROVIDER, "upstream request failed")
        text = response.text
    except requests.RequestException:
        # Requests exceptions may contain the credential-bearing URL.
        raise ProviderError(PROVIDER, "upstream request failed") from None
    return _parse_snapshot(text, settings.firms_source)


def _parse_csv(text: str, source: str) -> list[FireEvent]:
    return _parse_snapshot(text, source).fires


def _measurement(row, name, problems):
    raw = row.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
        if not math.isfinite(value) or (name == "frp" and value < 0):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        problems.append("invalid_numeric")
        return None


def _parse_snapshot(text: str, source: str) -> FireSnapshot:
    fires, observations, unlocated = [], [], []
    try:
        reader = csv.DictReader(StringIO(text.lstrip("\ufeff")), strict=True)
        headers = reader.fieldnames
        if not headers or not REQUIRED_COLUMNS.issubset(headers) or len(headers) != len(set(headers)):
            raise ProviderError(PROVIDER, "unrecognizable CSV response")
        for row in reader:
            problems = []
            try:
                date = (row["acq_date"] or "").strip()
                time = (row["acq_time"] or "").strip()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{1,4}", time):
                    raise ValueError()
                observed_at = datetime.strptime(date + time.zfill(4), "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
                lat, lon = float(row["latitude"]), float(row["longitude"])
                if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):
                    raise ValueError()
            except (ValueError, TypeError):
                unlocated.append("invalid_position_or_time")
                continue
            if None in row or any(value is None for value in row.values()):
                problems.append("malformed_row")
            if not MODEL_COLUMNS.issubset(headers):
                problems.append("missing_model_columns")
            frp = _measurement(row,"frp",problems)
            brightness4 = _measurement(row,"bright_ti4",problems)
            brightness5 = _measurement(row,"bright_ti5",problems)
            satellite = (row.get("satellite") or "").strip()
            confidence = (row.get("confidence") or "").strip().lower()
            daynight = (row.get("daynight") or "").strip().upper()
            if not satellite or confidence not in ("l","n","h") or daynight not in ("D","N"):
                problems.append("invalid_classification")
            fire_type = None
            if "type" in headers:
                raw_type = (row.get("type") or "").strip()
                if raw_type in ("0","1","2","3"):
                    fire_type = int(raw_type)
                else:
                    problems.append("invalid_type")
            identity = f"{source}|{observed_at.isoformat()}|{lat}|{lon}"
            fire_id = "firms:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            observations.append(ModelObservation(fire_id,lat,lon,observed_at,satellite,confidence,
                                brightness4,brightness5,frp,daynight,fire_type,tuple(problems)))
            # Preserve the public adapter's original validation and ID contract.
            if None in row:
                continue
            try:
                raw_frp = (row.get("frp") or "").strip()
                fires.append(FireEvent(id=fire_id,latitude=lat,longitude=lon,observed_at=observed_at,
                                       frp_mw=float(raw_frp) if raw_frp else None,source=PROVIDER))
            except (ValueError, TypeError, ValidationError):
                continue
    except csv.Error:
        raise ProviderError(PROVIDER, "malformed CSV response") from None
    return FireSnapshot(fires,observations,frozenset(headers),tuple(unlocated))
