"""Shared data types. Every value keeps its evidence; every gap becomes an ``Unknown``.

Three dates are never mixed (PLANS.md 5.3):
- ``period_end``: the end of the accounting period a value describes
- ``published_at``: the date the value became public (filing date)
- ``retrieved_at``: when this system fetched it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Evidence:
    source: str  # sec | dart | document
    title: str
    url: str  # human-openable link, no credentials
    published_at: str = ""
    retrieved_at: str = field(default_factory=now_utc)
    locator: str = ""  # section or field inside the document
    quote: str = ""  # verbatim source text the value was read from


@dataclass
class Unknown:
    code: str
    message: str  # digit-free, safe to pass to an LLM
    detail: str = ""  # may contain numbers, UI only


@dataclass(frozen=True)
class Fact:
    """One reported value as it appeared in one filing."""

    concept: str  # e.g. us-gaap:Revenues
    unit: str
    period_start: str | None  # None for instant (balance sheet) values
    period_end: str
    value: float
    published_at: str  # filing date, YYYY-MM-DD
    document_id: str  # SEC accession number / DART rcept_no
    form: str  # 10-K, 10-Q, 8-K, 사업보고서 ...
    source: str = "sec"
    url: str = ""

    @property
    def key(self) -> tuple:
        """Identity of the economic quantity, independent of which filing reported it."""
        return (self.concept, self.unit, self.period_start, self.period_end)

    @property
    def days(self) -> int | None:
        if not self.period_start:
            return None
        return (datetime.fromisoformat(self.period_end) - datetime.fromisoformat(self.period_start)).days + 1

    def evidence(self) -> Evidence:
        return Evidence(self.source, f"{self.form} {self.document_id}", self.url, published_at=self.published_at,
                        locator=f"{self.concept} {self.period_start or ''}~{self.period_end}")
