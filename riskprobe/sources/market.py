"""Which public filing source serves a query: DART for Korean companies, SEC otherwise.

A Korean company is written ``KR:<stock code>`` (what the app's search returns) or by a name
in Hangul. Everything else (ticker, CIK, English name) goes to SEC.
"""

from __future__ import annotations

from datetime import date

from riskprobe import config
from riskprobe.sources import dart, rates
from riskprobe.sources.sec import Candidate, SecSource


def is_kr(query: str) -> bool:
    return dart.is_query(query)


def source_for(query: str, http):
    return dart.DartSource(http) if is_kr(query) else SecSource(http)


def since_for(as_of: str) -> str:
    """Earliest period end worth loading for an analysis on ``as_of`` (TTM, a year of trend, comparatives)."""
    return date(int(as_of[:4]) - config.DART_YEARS_BEFORE, 1, 1).isoformat()


def currency(query: str) -> str:
    return "KRW" if is_kr(query) else "USD"


def floating_rate(query: str) -> str:
    return rates.FLOATING[currency(query)]


def long_rate(query: str) -> str:
    return rates.LONG[currency(query)]


def search(query: str, http, limit: int = 10) -> list[Candidate]:
    """Candidates from both markets: Hangul or KR: only DART; otherwise SEC first, then DART."""
    out: list[Candidate] = []
    d = dart.DartSource(http)
    if not is_kr(query):
        s = SecSource(http)
        if s.available()[0]:
            out += s.search(query, limit)
    if d.available()[0]:
        out += d.search(query, limit)
    return out[:limit] if is_kr(query) else out[: limit + 5]
