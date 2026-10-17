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

# Default rules (PLANS.md 2.4, 7.1). Used only when neither the user nor a filing gives a
# threshold, always labeled "기본 규칙" with the source, and changeable by the user.
# There is no single market standard (docs/p1_findings.md). The values sit inside commonly
# cited ranges: maintenance covenants ~2.0-3.0x minimum interest coverage and ~4.0-6.0x
# maximum leverage; S&P's financial risk matrix puts debt/EBITDA above 5x in its most
# leveraged band; US leveraged lending guidance (2013) flags total debt/EBITDA above 6x.
# Thresholds: indicator -> floor (coverage) or cap (leverage).
DEFAULT_THRESHOLDS = {"interest_coverage": 2.0, "net_debt_to_ebitda": 5.0,
                      "interest_coverage_adjusted": 2.0, "net_debt_to_ebitda_adjusted": 5.0}
DEFAULT_THRESHOLD_BASIS = ("보편 범위 내 값: 유지 약정 이자보상배율 최저 약 2~3배, 레버리지 최고 약 4~6배, "
                           "S&P 재무위험 매트릭스 최고 레버리지 구간 5배 초과, 미국 레버리지 대출 지침 6배 초과 주의")
# Headroom grade: a shock smaller than this (but above zero) is "근접".
HEADROOM_NEAR = {"%": 15.0, "bp": 100.0}
# A rate shock beyond this is shown as "insensitive" rather than as a literal figure.
RATE_SHOCK_CAP_BP = 1_000.0

# LLM (filing extraction and report wording only). Provider "auto" picks Gemini when a Google
# key is set, then Anthropic, else none (everything still runs, without extraction).
LLM_PROVIDER = os.environ.get("RISKPROBE_LLM_PROVIDER", "auto")  # auto | gemini | anthropic | none
GEMINI_MODEL = os.environ.get("RISKPROBE_GEMINI_MODEL", "gemini-3.5-flash-lite")
ANTHROPIC_MODEL = os.environ.get("RISKPROBE_ANTHROPIC_MODEL", "claude-haiku-5-5")
LLM_CACHE = os.environ.get("RISKPROBE_LLM_CACHE", "1") != "0"
LLM_CACHE_DIR = Path(os.environ.get("RISKPROBE_LLM_CACHE_DIR", DATA_DIR / "llm_cache"))
# Filing text sent to the model: keyword-selected paragraphs up to this many characters.
EXTRACT_MAX_CHARS = 120_000
