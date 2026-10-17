# LinuxONE runbook

## Environment and evidence

The teammate-reported host is Ubuntu 24.04.5 LTS on IBM LinuxONE (s390x),
user linux1, checkout ~/wildfyre, with Python 3.12.x and backend/.venv.
Earlier live deployment was reported with 267 tests passing; its exact deployed
revision and raw logs were not supplied. Local checks of the current model/API
are documented in the [verification record](verification.md).

The user accepted closing WF09 without an additional server check. This is
acceptance of the local implementation, not independent proof of LinuxONE
inference. The instructions below describe the shipped startup workflow.

## Start live mode

On your workstation, open the existing authorized SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 linuxone-wildfyre
```

In the LinuxONE shell:

```bash
cd ~/wildfyre
git status --short --branch
git pull --ff-only
./run.sh --live
```

Inspect unexpected local changes or branches before pulling. If the checkout
does not exist, clone the repository using your existing authorized Git access.
Stop any known previous backend in its terminal before starting this process.

Open [the dashboard](http://127.0.0.1:8000/app/) on your workstation. One FastAPI
process serves UI/API on loopback 8000; no separate frontend server is required.
Keep the SSH tunnel open. Ctrl+C stops the foreground application.

Python 3.12+ and venv support must already be installed. The launcher creates or
reuses backend/.venv and installs pinned runtime requirements only if needed.
First-time dependency installation needs network access; it never uses system pip.

## Key and model preparation

Live startup asks privately for FIRMS_MAP_KEY if it is not already exported.
The key is held in memory, not written to a file. Noninteractive startup requires
the variable in the process environment. No .env file is auto-loaded.

The reviewed 7,742,804-byte forest is included in the Git checkout at
models/fire-persistence/forest.json.gz. Startup verifies size/SHA-256, atomically
prepares artifacts/fire-persistence/forest.json.gz and reuses a verified cache.
It does not download private release assets or require a second GitHub credential.
No sklearn, pandas, historical CSVs, pickle loading or training is needed to run.

Startup must report **Model startup self-check: passed · wf08-rf-v1**.
A missing/corrupt required model stops the launcher; direct API startup can
instead expose unavailable ML while retaining the rule-based application.
Optional model paths and other settings are in
[backend/.env.example](../backend/.env.example).

## Sample and local use

```bash
./run.sh --sample
```

Sample mode makes no FIRMS/GBIF calls and uses fixed synthetic model inputs
ending 2026-10-17T06:00:00Z. With dependencies installed, model preparation
requires no network access. Leaflet/OpenStreetMap assets still use browser
network access. Follow [README](../README.md) for Windows startup.

## Check the running application

Through the same tunnel, from a second workstation terminal:

```powershell
curl.exe http://127.0.0.1:8000/
curl.exe http://127.0.0.1:8000/model/status
curl.exe http://127.0.0.1:8000/risk
```

Health returns {"project":"WildFyre","status":"running"}. Model status should be
ready with self-check passed. Risk includes separate fire_persistence and
proximity candidates. An empty latest model window can be valid; do not force
a score or relabel samples as live. To document a future remote check, retain
the revision, uname -m, Python version, startup self-check and redacted results.

## Interpretation

The model uses the latest closed six-hour UTC window to score another
same-cell detection during the following 24h. It does not use the still-open
window or choose stale data to create a prediction. Satellite delivery may lag.

Only VIIRS_SNPP_NRT is supported for live inference. Historical training used
SP vegetation fires, while NRT may lack vegetation type, so transfer scores
remain experimental. Missing required inputs yield unavailable results rather
than invented zeros. Scores are not fire spread, arrival, animal-danger or
evacuation predictions.

Refresh is automatic every five minutes while visible and idle, and pauses
when a timing candidate is selected. Manual Refresh data clears selection.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Python/venv or package setup fails | Inspect the host Python version, venv support and pinned-package error; do not use system pip. |
| Model preparation/self-check fails | Check the complete Git checkout and matching model.json/forest; restore a missing/corrupt tracked bundle. Remove only a known invalid cache if necessary. |
| Missing key in noninteractive mode | Supply FIRMS_MAP_KEY securely or use the interactive hidden prompt. |
| Live 503 | Check provider connectivity/key; live failures never switch to samples. |
| Empty/unavailable predictions | Inspect the displayed UTC interval, fixed reason codes and source product; no eligible current-window observations can be legitimate. |
| Port 8000 occupied | Stop the known previous server in its own terminal or inspect ownership before touching other processes. |
| Permission denied on run.sh | Run bash ./run.sh --live; the tracked file uses LF and an executable Git mode. |
| Dashboard cannot connect | Keep forwarding active and use /app/ with its trailing slash. |
