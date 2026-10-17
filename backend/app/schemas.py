"""Shared normalized provider and assessment contracts."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, model_validator

DataMode = Literal["live", "sample"]
Priority = Literal["UNASSESSED", "ALTERNATIVE RESPONSE", "CRITICAL", "HIGH", "MODERATE"]
UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Finite = Annotated[float, Field(allow_inf_nan=False, strict=True)]


class Location(BaseModel):
    latitude: Latitude
    longitude: Longitude


class FireEvent(Location):
    id: str
    observed_at: UTCDateTime
    frp_mw: Nonnegative | None
    source: Literal["NASA FIRMS"]


class WildlifeOccurrence(Location):
    id: str
    species: str
    observed_at: str | None
    dataset_key: str | None
    license: str | None
    source: Literal["GBIF"]


class ResponseMetadata(BaseModel):
    mode: DataMode
    fetched_at: UTCDateTime


class FireResponse(ResponseMetadata):
    fires: list[FireEvent]


class WildlifeResponse(ResponseMetadata):
    occurrences: list[WildlifeOccurrence]
    truncated: bool


class ZoneAssessment(Location):
    id: str
    name: str
    species: str
    nearest_fire_id: str
    distance_to_fire_km: Nonnegative
    risk: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
    risk_method: Literal["proximity"]
    fire_eta_minutes: Nonnegative | None
    response_time_minutes: Nonnegative | None
    safety_buffer_minutes: Nonnegative | None
    response_window_minutes: Finite | None
    priority: Priority


class PersistenceCell(Location):
    id: str
    grid_x: int
    grid_y: int
    fire_ids: list[str]
    fire_count: Annotated[int, Field(ge=1)]
    score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)] | None
    reason: str | None

    @model_validator(mode="after")
    def score_or_reason(self):
        if (self.score is None) != (self.reason is not None):
            raise ValueError("A cell requires either a score or an unavailable reason")
        return self


class PersistenceReport(BaseModel):
    status: Literal["ready", "empty", "unavailable"]
    reason: str | None
    model_version: str | None
    method: Literal["random_forest"]
    source_product: str
    mode: DataMode
    experimental: bool
    quality_flags: list[str]
    window_start: UTCDateTime
    window_end: UTCDateTime
    horizon_end: UTCDateTime
    cells: list[PersistenceCell]


class RiskResponse(ResponseMetadata):
    # Pure proximity builders may omit ML; the /risk route always supplies it.
    fire_persistence: PersistenceReport | None = None
    fires: list[FireEvent]
    occurrences: list[WildlifeOccurrence]
    wildlife_zones: list[ZoneAssessment]
    truncated: bool


class TimingScenario(BaseModel):
    zone: ZoneAssessment
    fire_eta_minutes: Nonnegative
    response_time_minutes: Nonnegative
    safety_buffer_minutes: Nonnegative


class ScenarioResponse(BaseModel):
    assessment: ZoneAssessment
    timing_source: Literal["operator_scenario"]
