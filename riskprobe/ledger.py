"""Assumption ledger: the record that links Probe, Watch and Audit (PLANS.md 2.3).

Probe writes what must stay true for an investment decision and where it would break. Watch
re-evaluates those entries when something changes; Audit replays them from ``recorded_at``.
Entries are stored as JSON, one file per ledger, and never edited in place: a status change is
appended to ``history``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from riskprobe.models import now_utc

THRESHOLD_SOURCES = ("user", "disclosed", "default_rule")
STATUSES = ("supported", "weakened", "mixed", "insufficient")


@dataclass
class Threshold:
    value: float
    source: str  # user | disclosed | default_rule
    note: str = ""  # quote and link for "disclosed", rule name for "default_rule"

    def __post_init__(self):
        if self.source not in THRESHOLD_SOURCES:
            raise ValueError(f"threshold source must be one of {THRESHOLD_SOURCES}")


@dataclass
class StatusEntry:
    as_of: str
    status: str
    reason: str
    evidence_urls: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")


@dataclass
class Assumption:
    id: str
    statement: str
    type: str  # financial | demand | competition | operations | macro
    indicator: str  # indicators.compute key, or "" when not quantifiable
    direction: str  # above | below: the side of the threshold where the assumption holds
    threshold: Threshold | None = None
    path_template: str = ""  # reverse.TEMPLATES key
    horizon: str = ""
    source_quote: str = ""
    source_url: str = ""
    recorded_at: str = ""  # as-of date of the decision
    user_confirmed: bool = False
    history: list[StatusEntry] = field(default_factory=list)
    # Values recorded with the decision that later checks need but filings may not carry in
    # structured form, e.g. floating_debt for the rate path (with its source in input_notes).
    inputs: dict[str, float] = field(default_factory=dict)
    input_notes: list[str] = field(default_factory=list)

    def holds(self, value: float) -> bool | None:
        if self.threshold is None:
            return None
        return value >= self.threshold.value if self.direction == "above" else value <= self.threshold.value


@dataclass
class Ledger:
    entity: str  # ticker or CIK
    name: str
    created_at: str = field(default_factory=now_utc)
    assumptions: list[Assumption] = field(default_factory=list)

    def add(self, a: Assumption) -> Assumption:
        if any(x.id == a.id for x in self.assumptions):
            raise ValueError(f"duplicate assumption id {a.id}")
        self.assumptions.append(a)
        return a

    def record(self, assumption_id: str, entry: StatusEntry) -> None:
        a = next(x for x in self.assumptions if x.id == assumption_id)
        a.history.append(entry)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        d = json.loads(path.read_text(encoding="utf-8"))
        items = []
        for a in d.pop("assumptions"):
            th = a.pop("threshold")
            hist = [StatusEntry(**h) for h in a.pop("history")]
            items.append(Assumption(**a, threshold=Threshold(**th) if th else None, history=hist))
        return cls(**d, assumptions=items)
