"""HTTP client with a disk cache and per-host pacing.

Sources receive an ``Http`` instance, so tests swap in ``tests/fakes.FakeHttp`` and run
without network or keys. Credentials (``config.SECRET_PARAMS``, auth, headers) never enter a
cache key or an evidence URL.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import requests

from riskprobe import config


class FetchError(RuntimeError):
    pass


@dataclass
class Response:
    status: int
    content: bytes
    url: str  # public URL (secrets stripped)
    from_cache: bool = False

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def public_url(url: str, params: dict | None = None) -> str:
    clean = {k: v for k, v in (params or {}).items() if k not in config.SECRET_PARAMS}
    return f"{url}?{urlencode(clean)}" if clean else url


class Http:
    def __init__(self, cache: bool | None = None, ttl_hours: float | None = None):
        self._session = requests.Session()
        self._ttl = config.HTTP_CACHE_TTL_HOURS if ttl_hours is None else ttl_hours
        self._cache = None
        if config.HTTP_CACHE if cache is None else cache:
            try:
                import diskcache

                self._cache = diskcache.Cache(str(config.CACHE_DIR / "http"), size_limit=500 * 2**20)
            except Exception:  # noqa: BLE001 - caching is an optimization only
                self._cache = None
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _pace(self, host: str) -> None:
        gap = config.MIN_INTERVAL_SEC.get(host, 0.0)
        if not gap:
            return
        with self._lock:
            wait = self._last.get(host, 0.0) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, headers: dict | None = None,
            auth: tuple[str, str] | None = None, ttl_hours: float | None = None) -> Response:
        """GET with caching of 200 and 404 answers. Raises FetchError on network errors and 5xx."""
        pub = public_url(url, params)
        key = hashlib.sha256(pub.encode("utf-8")).hexdigest()
        ttl = self._ttl if ttl_hours is None else ttl_hours
        if self._cache is not None and ttl > 0:
            hit = self._cache.get(key)
            if hit is not None:
                return Response(hit[0], hit[1], pub, from_cache=True)
        self._pace(urlparse(url).netloc)
        try:
            r = self._session.get(url, params=params, headers=headers, auth=auth, timeout=config.HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise FetchError(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
        if r.status_code >= 500 or r.status_code == 429:
            raise FetchError(f"HTTP {r.status_code} from {urlparse(url).netloc}")
        resp = Response(r.status_code, r.content, pub)
        if self._cache is not None and ttl > 0 and r.status_code in (200, 404):
            self._cache.set(key, (r.status_code, r.content), expire=ttl * 3600)
        return resp
