# WildFyre

Wildfire and wildlife decision support for the IBM Datathon, built with FastAPI
and a Leaflet dashboard for deployment on IBM LinuxONE.

WildFyre combines NASA FIRMS fire detections, GBIF animal observations, a trained
fire-persistence model and hypothetical response timing. It keeps those signals
separate: proximity measures distance, the model estimates another same-cell
fire detection, and timing comes from the operator.

## Start the application

On the existing LinuxONE checkout:

```bash
cd ~/wildfyre
git pull --ff-only
./run.sh --live
```

The launcher creates or reuses `backend/.venv`, installs missing pinned backend
packages, verifies the bundled model and asks privately for a FIRMS map key if
one is not already exported. It runs one foreground process for both the API
and dashboard. Python 3.12+ with venv support is required; first-time package
installation needs network access. No scientific packages or additional GitHub
credential are required to serve the bundled model.

On your workstation, keep the SSH tunnel open:

```bash
ssh -L 8000:127.0.0.1:8000 linuxone-wildfyre
```

Open [the dashboard](http://127.0.0.1:8000/app/) or
[API documentation](http://127.0.0.1:8000/docs).
Use `./run.sh --sample` for deterministic sample data without provider calls.
Leaflet assets and OpenStreetMap tiles still need browser network access.

For Windows development, from the repository root:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
cd backend
.venv/Scripts/python.exe -m app.startup --sample
```

Use `--live` instead for live providers. Stop the foreground process with Ctrl+C.
Detailed setup and troubleshooting are in the [runbook](docs/linuxone-runbook.md).

## What the dashboard shows

- **Fire detections:** FIRMS location, UTC acquisition time and fire radiative
  power in MW. A detection is an observation, not a fire perimeter.
- **Animal observations:** GBIF Animalia records with observation dates,
  attribution and licenses. Historical occurrences do not establish current
  animal presence or habitat boundaries.
- **Proximity candidates:** observations within 25 km of a fire detection.
  The score is `max(0, 1 − distance_km / 25)`, not a calibrated probability.
- **Fire persistence:** a Random Forest score for another qualifying detection
  in the same approximate 5 km cell during the next 24 hours, based on the latest
  closed six-hour UTC window. Live NRT transfer is explicitly experimental.
- **Operator timing:** enter hypothetical fire ETA, response time and safety
  buffer. The response window is ETA minus response time minus buffer;
  `95 − 40 − 20 = 35` minutes. Unknown times remain unassessed; zero or negative
  windows give `ALTERNATIVE RESPONSE`.

Automatic refresh runs every five minutes while visible and idle. Selecting a
timing candidate pauses it to preserve inputs; manual **Refresh data** clears
the selection. Provider failures stay visible and never switch to sample data.

## Configuration

Export settings before startup; `.env` is not loaded automatically.
[backend/.env.example](backend/.env.example) lists the available settings.

| Setting | Default / purpose |
| --- | --- |
| `FIRMS_MAP_KEY` | Required in live mode; hidden prompt if absent in an interactive launcher. |
| `FIRMS_SOURCE` | `VIIRS_SNPP_NRT`; the supported live model product. |
| `WILDFYRE_BBOX` | `-124.5,32.5,-114.0,42.1` in west,south,east,north order. |
| `WILDFYRE_DATA_MODE` | `live` for direct API startup; launcher flags choose live/sample explicitly. |
| `WILDFYRE_ALLOWED_ORIGINS` | Loopback port 8080 origins for optional separately hosted frontend use. |
| `WILDFYRE_REQUIRE_MODEL` | Launcher sets `1`; direct API defaults to visible rule-only fallback. |
| `WILDFYRE_MODEL_CONTRACT` / `WILDFYRE_MODEL_ARTIFACT` | Optional paths overriding repository defaults. |

The normal `/app/` dashboard uses the same API origin. For a separately hosted
frontend, set a reachable API URL in `frontend/config.js` and matching CORS
origins. A remote browser's loopback address refers to that browser's machine.

## Documentation

- [Architecture and API](docs/architecture.md)
- [LinuxONE setup and troubleshooting](docs/linuxone-runbook.md)
- [Model, evaluation and limitations](docs/fire-persistence-model.md)
- [Verification and acceptance record](docs/verification.md)

## Verification

Install development dependencies and run the offline backend suite:

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```

On Linux use `backend/.venv/bin/python`. Browser checks require Node,
Playwright and Microsoft Edge:

```bash
node frontend/tests/browser.cjs
node frontend/tests/request-timeout.cjs
```

Notebook/export verification uses its own
[scientific requirements](notebooks/requirements-fire-persistence.txt), separate
from application serving. See the verification record for actual results.

WF09 was closed at the user's request after local acceptance. LinuxONE inference
was not independently verified in this session; closure does not assert a remote
test pass. The project does not predict fire spread, fire arrival, animal danger
probability or evacuation need.
