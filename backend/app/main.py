"""FastAPI routes with explicit configuration and provider boundaries."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
import requests

from app.config import DEFAULT_ORIGINS, ROOT, Settings, load_settings
from app.schemas import FireResponse, RiskResponse, ScenarioResponse, TimingScenario, WildlifeResponse
from app.services.decisions import build_risk_snapshot, evaluate_scenario
from app.services.errors import ProviderError
from app.services.firms import fetch_fires, fetch_fire_snapshot
from app.services.persistence import initialize_model, build_persistence
from app.services.gbif import fetch_occurrences


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_fetched_at():
    return datetime.now(timezone.utc)


def get_clock():
    return get_fetched_at


def get_model_state(request: Request):
    return request.app.state.model


def get_session():
    with requests.Session() as session:
        yield session


def create_app(settings: Settings | None = None) -> FastAPI:
    # Snapshot environment once so CORS and lifespan use identical configuration.
    environ = dict(os.environ) if settings is None else None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.settings = settings if settings is not None else load_settings(environ)
        application.state.model = initialize_model(application.state.settings)
        if application.state.settings.require_model:
            print("Model startup self-check: passed · " + application.state.model.model.model_version, flush=True)
        yield

    application = FastAPI(title="WildFyre API", lifespan=lifespan)
    application.add_exception_handler(RequestValidationError, validation_error_response)
    origins = settings.allowed_origins if settings is not None else tuple(
        value.strip() for value in environ.get("WILDFYRE_ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",") if value.strip()
    )
    application.add_middleware(
        CORSMiddleware, allow_origins=list(origins), allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    application.add_api_route("/", root, methods=["GET"])
    application.add_api_route("/risk", get_risk, methods=["GET"], response_model=RiskResponse)
    application.add_api_route("/risk/evaluate", post_scenario, methods=["POST"], response_model=ScenarioResponse)
    application.add_api_route("/wildlife", get_wildlife, methods=["GET"], response_model=WildlifeResponse)
    application.add_api_route("/fires", get_fires, methods=["GET"], response_model=FireResponse)
    application.add_api_route("/model/status", model_status, methods=["GET"])
    application.mount("/app", StaticFiles(directory=ROOT / "frontend", html=True), name="dashboard")
    return application


async def validation_error_response(_request: Request, error: RequestValidationError):
    # Raw rejected NaN/Infinity values cannot be serialized as JSON. Return only
    # the useful validation fields, without echoing posted input or exception context.
    return JSONResponse(status_code=422, content={
        "detail": [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                   for item in error.errors()],
    })


def root():
    return {"project": "WildFyre", "status": "running"}


def get_fires(settings: Settings = Depends(get_settings), session: requests.Session = Depends(get_session)):
    try:
        fires = fetch_fires(settings, session)
    except ProviderError:
        # Neither raw Requests exceptions nor provider response bodies reach clients.
        raise HTTPException(status_code=503, detail="NASA FIRMS data is temporarily unavailable") from None
    return FireResponse(fires=fires, mode=settings.data_mode, fetched_at=datetime.now(timezone.utc))


def get_wildlife(settings: Settings = Depends(get_settings), session: requests.Session = Depends(get_session)):
    try:
        occurrences, truncated = fetch_occurrences(settings, session)
    except ProviderError:
        raise HTTPException(status_code=503, detail="GBIF data is temporarily unavailable") from None
    return WildlifeResponse(
        occurrences=occurrences, truncated=truncated,
        mode=settings.data_mode, fetched_at=datetime.now(timezone.utc),
    )


def model_status(state=Depends(get_model_state)):
    return {"status": state.status, "reason": state.reason,
            "model_version": state.model.model_version if state.model else None,
            "self_check": "passed" if state.model else "unavailable"}


def get_risk(settings: Settings = Depends(get_settings), session: requests.Session = Depends(get_session),
             clock=Depends(get_clock), state=Depends(get_model_state)):
    try:
        snapshot = fetch_fire_snapshot(settings, session)
        occurrences, truncated = fetch_occurrences(settings, session)
    except ProviderError:
        raise HTTPException(status_code=503, detail="Risk data is temporarily unavailable") from None
    fetched_at = clock()
    result = build_risk_snapshot(snapshot.fires, occurrences, mode=settings.data_mode,
                                 fetched_at=fetched_at, truncated=truncated)
    result.fire_persistence = build_persistence(snapshot, state, fetched_at, settings.data_mode, settings.firms_source)
    return result


def post_scenario(scenario: TimingScenario):
    try:
        return evaluate_scenario(scenario)
    except ValidationError:
        # Individually finite durations can still overflow when subtracted.
        raise HTTPException(status_code=422, detail="Scenario response window exceeds the supported numeric range") from None


app = create_app()
