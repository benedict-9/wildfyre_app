"""Prepare a verified serving model and run one foreground dashboard/API process."""
import argparse
import getpass
import json
import os
import sys

import uvicorn

from app.config import load_settings
from app.models.artifacts import prepare_artifact, verify_artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--sample", action="store_true")
    args = parser.parse_args(argv)
    environ = dict(os.environ)
    environ["WILDFYRE_DATA_MODE"] = "sample" if args.sample else "live"
    environ["WILDFYRE_REQUIRE_MODEL"] = "1"
    try:
        if not args.sample and not environ.get("FIRMS_MAP_KEY", "").strip():
            if not sys.stdin.isatty():
                raise ValueError("Export FIRMS_MAP_KEY for noninteractive startup")
            environ["FIRMS_MAP_KEY"] = getpass.getpass("FIRMS map key (hidden, not saved): ").strip()
        settings = load_settings(environ)
        contract = json.loads(settings.model_contract_path.read_text(encoding="utf-8"))
        try:
            verify_artifact(settings.model_artifact_path, contract["serving_artifact"])
        except (OSError, ValueError):
            path = prepare_artifact(settings.model_contract_path, settings.model_artifact_path.parent)
            environ["WILDFYRE_MODEL_ARTIFACT"] = str(path)
            settings = load_settings(environ)
        from app.main import create_app
        print("WildFyre: http://127.0.0.1:8000/app/", flush=True)
        print("Tunnel: ssh -L 8000:127.0.0.1:8000 linuxone-wildfyre", flush=True)
        print("Mode: " + settings.data_mode + " · model integrity verified; startup self-check follows.", flush=True)
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8000)
        return 0
    except (ValueError, OSError, KeyError, TypeError, EOFError):
        print("Startup failed: check FIRMS configuration, model contract/integrity and download connectivity.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
