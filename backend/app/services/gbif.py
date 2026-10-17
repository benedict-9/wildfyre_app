"""Bounded Animalia occurrence retrieval; observations do not establish presence."""

import math

from pydantic import ValidationError
import requests

from app.config import BoundingBox, GBIF_MAX_PAGES, GBIF_PAGE_SIZE, REQUEST_TIMEOUT, Settings
from app.data import sample_wildlife_occurrences
from app.schemas import WildlifeOccurrence
from app.services.errors import ProviderError


_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
_ANIMALIA_KEY = 1


def _parse_occurrence(row: object, bbox: BoundingBox) -> WildlifeOccurrence | None:
    if not isinstance(row, dict):
        return None
    kingdom_key = row.get("kingdomKey")
    if type(kingdom_key) is not int or kingdom_key != _ANIMALIA_KEY:
        return None
    key = row.get("key")
    if isinstance(key, bool) or not isinstance(key, (int, str)):
        return None
    if isinstance(key, str) and (not key.isascii() or not key.isdecimal()):
        return None
    try:
        if int(key) <= 0:
            return None
        latitude = row.get("decimalLatitude")
        longitude = row.get("decimalLongitude")
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            return None
        latitude, longitude = float(latitude), float(longitude)
        west, south, east, north = bbox
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            return None
        if not (south <= latitude <= north and west <= longitude <= east):
            return None
        species = next((value.strip() for value in (row.get("species"), row.get("scientificName"))
                        if isinstance(value, str) and value.strip()), "Unknown species")
        return WildlifeOccurrence(
            id=str(int(key)), species=species, latitude=latitude, longitude=longitude,
            observed_at=row.get("eventDate"), dataset_key=row.get("datasetKey"),
            license=row.get("license"), source="GBIF",
        )
    except (TypeError, ValueError, OverflowError, ValidationError):
        # A malformed individual record must not erase usable observations.
        return None


def _validate_page(payload: object, offset: int) -> tuple[list, bool]:
    if not isinstance(payload, dict):
        raise ProviderError("GBIF", "Malformed occurrence response")
    rows = payload.get("results")
    valid = isinstance(rows, list) and len(rows) <= GBIF_PAGE_SIZE
    valid = valid and type(payload.get("endOfRecords")) is bool
    valid = valid and type(payload.get("offset")) is int and payload["offset"] == offset
    valid = valid and type(payload.get("limit")) is int and payload["limit"] == GBIF_PAGE_SIZE
    valid = valid and type(payload.get("count")) is int and payload["count"] >= 0
    if not valid:
        raise ProviderError("GBIF", "Malformed occurrence response")
    return rows, payload["endOfRecords"]


def fetch_occurrences(settings: Settings, session: requests.Session) -> tuple[list[WildlifeOccurrence], bool]:
    """Fetch up to three 100-record pages, raising rather than returning partial data."""
    if settings.data_mode == "sample":
        return [WildlifeOccurrence.model_validate(row) for row in sample_wildlife_occurrences], False

    west, south, east, north = settings.bbox
    occurrences: list[WildlifeOccurrence] = []
    seen: set[str] = set()
    for page_number in range(GBIF_MAX_PAGES):
        offset = page_number * GBIF_PAGE_SIZE
        params = {
            "hasCoordinate": "true",
            "kingdomKey": _ANIMALIA_KEY,
            "decimalLatitude": f"{south},{north}",
            "decimalLongitude": f"{west},{east}",
            "limit": GBIF_PAGE_SIZE,
            "offset": offset,
        }
        try:
            response = session.get(_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            # Suppress the upstream exception chain: URLs or response text can contain secrets.
            raise ProviderError("GBIF", "Occurrence request failed") from None
        rows, end_of_records = _validate_page(payload, offset)
        for row in rows:
            occurrence = _parse_occurrence(row, settings.bbox)
            if occurrence is not None and occurrence.id not in seen:
                seen.add(occurrence.id)
                occurrences.append(occurrence)
        if end_of_records:
            return occurrences, False
    return occurrences, True
