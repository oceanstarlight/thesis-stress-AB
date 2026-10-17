"""Global configuration: paths, API keys and HTTP settings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a local, git-ignored .env file (existing env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
CACHE_DIR = Path(os.environ.get("RISKPROBE_CACHE_DIR", DATA_DIR / "cache"))


def env(name: str) -> str:
    """Read a key at call time so tests and the app can change it without re-import."""
    return os.environ.get(name, "").strip().strip('"').strip("'").strip()


# HTTP. Responses are cached on disk keyed by URL and non-secret params, so a re-run costs no
# API calls. Set RISKPROBE_HTTP_CACHE=0 to disable.
HTTP_TIMEOUT = 60
HTTP_CACHE = os.environ.get("RISKPROBE_HTTP_CACHE", "1") != "0"
HTTP_CACHE_TTL_HOURS = float(os.environ.get("RISKPROBE_HTTP_CACHE_TTL_HOURS", "24"))
# Query params that carry credentials; never part of a cache key or evidence URL.
SECRET_PARAMS = ("crtfc_key",)
# SEC asks for at most ten requests per second.
MIN_INTERVAL_SEC = {"www.sec.gov": 0.12, "data.sec.gov": 0.12}
