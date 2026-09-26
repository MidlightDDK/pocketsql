import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

from pocketsql.data.paths import RAW, SOURCES


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str) -> Path:
    """Download a pinned source into training/data/raw/, verifying its sha256."""
    source = json.loads(SOURCES.read_text(encoding="utf-8"))[name]
    dest = RAW / source["file"]
    expected = source["sha256"]
    if dest.exists() and (expected is None or sha256(dest) == expected):
        return dest
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    errors = []
    for url in source["urls"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pocketsql"})
            with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
        except OSError as e:
            errors.append(f"{url}: {e}")
            continue
        got = sha256(tmp)
        if expected is None or got == expected:
            tmp.replace(dest)
            return dest
        errors.append(f"{url}: sha256 {got} != {expected}")
    tmp.unlink(missing_ok=True)
    raise SystemExit(
        f"Could not download {name}. Download {source['file']} manually from "
        f"{source['homepage']} into {RAW}.\n" + "\n".join(errors)
    )
