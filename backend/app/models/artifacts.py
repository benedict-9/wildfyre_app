"""Bounded, integrity-checked public serving artifacts (never pickle)."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests

MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024


def verify_artifact(path: Path, descriptor: dict) -> None:
    size = descriptor.get("bytes")
    digest = descriptor.get("sha256")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise ValueError("Invalid artifact size")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid artifact digest")
    if path.stat().st_size != size:
        raise ValueError("Artifact size mismatch")
    actual = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            actual.update(block)
    if actual.hexdigest() != digest:
        raise ValueError("Artifact digest mismatch")


def prepare_artifact(contract_path: Path, cache_dir: Path, session=None) -> Path:
    """Download to a temporary sibling; a failure never replaces the cache."""
    descriptor = json.loads(contract_path.read_text(encoding="utf-8"))["serving_artifact"]
    path = cache_dir / "forest.json.gz"
    try:
        verify_artifact(path, descriptor)
        return path
    except (OSError, ValueError):
        pass
    # Private GitHub releases require separate HTTP credentials. The reviewed
    # serving forest ships with the checkout so git pull is sufficient.
    if "bundled_file" in descriptor:
        if descriptor["bundled_file"] != "forest.json.gz":
            raise ValueError("Invalid bundled artifact name")
        bundle = contract_path.parent / descriptor["bundled_file"]
        temp = None
        try:
            verify_artifact(bundle, descriptor)
            cache_dir.mkdir(parents=True, exist_ok=True)
            with bundle.open("rb") as source, tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".tmp", delete=False) as stream:
                temp = Path(stream.name)
                count = 0
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(block)
                    if count > descriptor["bytes"]:
                        raise ValueError("Bundled artifact exceeds size")
                    stream.write(block)
            verify_artifact(temp, descriptor)
            os.replace(temp, path)
            return path
        except (OSError, ValueError):
            raise ValueError("Bundled model preparation failed; pull the complete checkout again") from None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    url = descriptor.get("download_url", "")
    parsed = urlsplit(url)
    size = descriptor.get("bytes")
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or parsed.fragment or type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES):
        raise ValueError("Invalid artifact download descriptor")
    cache_dir.mkdir(parents=True, exist_ok=True)
    owned = session is None
    session = session or requests.Session()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            with session.get(url, stream=True, timeout=(3.05, 30)) as response:
                if response.status_code != 200:
                    raise ValueError("Artifact download failed")
                count = 0
                for block in response.iter_content(chunk_size=1024 * 1024):
                    count += len(block)
                    if count > size or count > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Artifact download exceeds size")
                    stream.write(block)
        verify_artifact(temp, descriptor)
        os.replace(temp, path)
        return path
    except (OSError, requests.RequestException, ValueError):
        raise ValueError("Artifact preparation failed; check network and model integrity") from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        if owned:
            session.close()
