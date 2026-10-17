#!/usr/bin/env bash
# One foreground application. No system pip, model training or background services.
set -euo pipefail
wfRoot="$(cd -- "$(dirname -- "$0")" && pwd)"
wfMode=--live
if [[ $# -gt 0 ]]; then wfMode=$1; fi
if [[ $# -gt 1 ]] || [[ "$wfMode" != --live && "$wfMode" != --sample ]]; then
  echo "Usage: ./run.sh [--live|--sample]" >&2
  exit 2
fi
cd -- "$wfRoot"
wfPython="$wfRoot/backend/.venv/bin/python"
if [[ ! -x "$wfPython" ]]; then
  python3 -m venv "$wfRoot/backend/.venv"
fi
if ! "$wfPython" - "$wfRoot/backend/requirements.txt" <<'PY'
import importlib.metadata
from pathlib import Path
import sys
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
try:
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, expected = line.strip().split("==")
        if importlib.metadata.version(name) != expected:
            raise SystemExit(1)
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
then
  "$wfPython" -m pip install --disable-pip-version-check -r "$wfRoot/backend/requirements.txt"
fi
cd -- "$wfRoot/backend"
exec "$wfPython" -m app.startup "$wfMode"
