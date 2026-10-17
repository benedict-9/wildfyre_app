"""Model lifecycle and explicit persistence outcomes, separate from proximity."""
from dataclasses import dataclass
import json

from app.config import Settings
from app.models.fire_model import ForestModel
from app.models.features import SAMPLE_CLOCK, build_cell_features
from app.schemas import PersistenceCell, PersistenceReport


@dataclass(frozen=True)
class ModelState:
    status: str
    reason: str | None
    model: ForestModel | None = None


def initialize_model(settings: Settings) -> ModelState:
    try:
        contract = json.loads(settings.model_contract_path.read_text(encoding="utf-8"))
        model = ForestModel.load(settings.model_artifact_path, contract)
        model.self_check()
        return ModelState("ready", None, model)
    except (OSError, ValueError, KeyError, TypeError):
        if settings.require_model:
            raise ValueError("Required model failed integrity or startup self-check") from None
        return ModelState("unavailable", "model_unavailable")


def build_persistence(snapshot, state, fetched_at, mode, source) -> PersistenceReport:
    batch = build_cell_features(snapshot, SAMPLE_CLOCK if mode == "sample" else fetched_at, source)
    flags = list(batch.quality_flags) if mode == "live" else ["synthetic_sample_inputs"]
    reason = state.reason or batch.reason
    if mode == "live" and source != "VIIRS_SNPP_NRT":
        reason = "unsupported_source"
    cells = []
    if not reason:
        for cell in batch.cells:
            score = None
            cell_reason = cell.reason
            if not cell_reason:
                try:
                    score = state.model.predict(cell.features)
                except ValueError:
                    cell_reason = "inference_failed"
            cells.append(PersistenceCell(id=cell.id, grid_x=cell.grid_x, grid_y=cell.grid_y,
                latitude=cell.latitude, longitude=cell.longitude, fire_ids=list(cell.fire_ids),
                fire_count=cell.fire_count, score=score, reason=cell_reason))
    status = "unavailable" if reason else "ready" if any(c.score is not None for c in cells) else "empty"
    if cells and status == "empty":
        status, reason = "unavailable", "no_scorable_cells"
    return PersistenceReport(status=status, reason=reason,
        model_version=state.model.model_version if state.model else None,
        method="random_forest", source_product=source, mode=mode,
        experimental=mode=="live", quality_flags=flags, window_start=batch.window_start,
        window_end=batch.window_end, horizon_end=batch.horizon_end, cells=cells)
