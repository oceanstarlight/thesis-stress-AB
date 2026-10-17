"""Point-in-time view of reported facts.

A fact is visible on date T only if its filing date is on or before T. For each economic
quantity (concept, unit, period) the value known on T is the one from the latest filing up to
T, so a later restatement replaces the original only from the restatement's filing date on.
Restated values are kept as separate versions, never overwritten.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from riskprobe import forms
from riskprobe.models import Fact, Unknown

BASIS_CHANGING_FORMS = forms.BASIS_CHANGING


@dataclass
class Snapshot:
    as_of: str
    facts: dict[tuple, Fact] = field(default_factory=dict)  # Fact.key -> value known on as_of
    unknowns: list[Unknown] = field(default_factory=list)
    # concept -> dates on which an annual report, an amendment or an 8-K recast changed an
    # earlier reported value of that concept. Values on either side of such a date may be on
    # different bases and must not be combined. A 10-Q that re-reports last year's quarter on
    # the basis a 10-K already set is catching up, not starting a new basis, so it does not
    # count. Known gap: a basis change first made in a 10-Q is not detected.
    restated_on: dict[str, set[str]] = field(default_factory=dict)

    def mixes_bases(self, facts: list[Fact]) -> bool:
        """True when ``facts`` straddle a restatement of their concept."""
        by_concept: dict[str, list[str]] = defaultdict(list)
        for f in facts:
            by_concept[f.concept].append(f.published_at)
        for concept, pubs in by_concept.items():
            lo, hi = min(pubs), max(pubs)
            if any(lo < r <= hi for r in self.restated_on.get(concept, ())):
                return True
        return False

    def get(self, concept: str, period_start: str | None, period_end: str, unit: str = "USD") -> Fact | None:
        return self.facts.get((concept, unit, period_start, period_end))

    def series(self, concept: str, unit: str = "USD", days: tuple[int, int] | None = None) -> list[Fact]:
        """Values of one concept ordered by period end. ``days`` filters durations, e.g.
        (80, 100) for quarters, (350, 380) for fiscal years; None keeps everything."""
        out = [f for f in self.facts.values() if f.concept == concept and f.unit == unit]
        if days is not None:
            out = [f for f in out if f.days is not None and days[0] <= f.days <= days[1]]
        return sorted(out, key=lambda f: (f.period_end, f.period_start or ""))


def visible(facts: list[Fact], as_of: str) -> list[Fact]:
    return [f for f in facts if f.published_at <= as_of]


def snapshot(facts: list[Fact], as_of: str, exclude: set[tuple] | None = None) -> Snapshot:
    """``exclude``: (document_id, key) pairs dropped beforehand, e.g. ``quality.screen`` output."""
    snap = Snapshot(as_of)
    by_key: dict[tuple, list[Fact]] = defaultdict(list)
    for f in visible(facts, as_of):
        if exclude and (f.document_id, f.key) in exclude:
            continue
        by_key[f.key].append(f)
    for key, fs in by_key.items():
        ordered = sorted(fs, key=lambda f: (f.published_at, f.document_id))
        for prev, f in zip(ordered, ordered[1:]):
            if f.value != prev.value and f.published_at != prev.published_at and f.form in BASIS_CHANGING_FORMS:
                snap.restated_on.setdefault(key[0], set()).add(f.published_at)
        latest_day = max(f.published_at for f in fs)
        same_day = sorted((f for f in fs if f.published_at == latest_day), key=lambda f: f.document_id)
        snap.facts[key] = same_day[-1]
        if len({f.value for f in same_day}) > 1:
            snap.unknowns.append(Unknown(
                "pit_same_day_conflict", "같은 날 제출된 서로 다른 공시가 같은 기간에 다른 값을 보고함, 접수번호가 늦은 값을 사용",
                f"{key}: {[(f.document_id, f.value) for f in same_day]}"))
    return snap


def versions(facts: list[Fact], key: tuple) -> list[Fact]:
    """Every report of one quantity in filing order, including unchanged repeats."""
    return sorted((f for f in facts if f.key == key), key=lambda f: (f.published_at, f.document_id))


def restatements(facts: list[Fact], key: tuple) -> list[tuple[Fact, Fact]]:
    """(previous, new) pairs where a later filing changed the value."""
    out, prev = [], None
    for f in versions(facts, key):
        if prev is not None and f.value != prev.value:
            out.append((prev, f))
        prev = f
    return out


def published_between(facts: list[Fact], after: str, until: str) -> list[Fact]:
    """Facts that became public in (after, until], ordered by filing date: the replay feed."""
    return sorted((f for f in facts if after < f.published_at <= until), key=lambda f: (f.published_at, f.document_id))


def leaks(snap: Snapshot) -> list[Fact]:
    """Facts in a snapshot that were not public on its date. Must always be empty."""
    return [f for f in snap.facts.values() if f.published_at > snap.as_of]
