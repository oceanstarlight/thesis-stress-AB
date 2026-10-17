"""Data quality rules applied before any analysis (P0 findings).

- Suspect values: a value outside the periods a periodic report normally states (its own
  period and the prior-year comparative) that also changes the value reported before. A 10-Q
  for March 2025 that states a September 2024 quarter differently from the 10-Q and 10-K
  before it is most likely a tagging error (seen in AES). Out-of-period values that repeat the
  earlier value are harmless (equity roll-forwards carry many) and stay. Suspects are excluded
  from point-in-time views by default.
- Recast filings: an 8-K can carry re-issued financial statements. Those values are valid
  but marked, so the UI can say the number came from a recast, not a periodic report.
"""

from __future__ import annotations

from datetime import date, timedelta

from riskprobe.models import Fact, Unknown

TOL = timedelta(days=10)
QUARTERLY = {"10-Q", "10-Q/A"}
ANNUAL = {"10-K", "10-K/A", "20-F", "40-F"}
RECAST = {"8-K", "8-K/A"}


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _near(a: date, b: date) -> bool:
    return abs(a - b) <= TOL


def out_of_period(fact: Fact, report_date: str) -> bool:
    """True when ``fact`` lies outside the periods a report for ``report_date`` normally states."""
    if not report_date or fact.concept.startswith("dei:"):  # cover page facts are dated at filing
        return False
    end, r = _d(fact.period_end), _d(report_date)
    if fact.period_start is None and r < end <= _d(fact.published_at):
        return False  # balance stated as of a date after the period end (subsequent events)
    if fact.form in QUARTERLY:
        if fact.period_start is None:  # balance sheet: this quarter end or the prior year end
            return not (r - timedelta(days=400) <= end <= r + TOL)
        return not (_near(end, r) or _near(end, r - timedelta(days=365)))
    if fact.form in ANNUAL:
        return not (r - timedelta(days=3 * 365) - TOL <= end <= r + TOL)
    return False


def screen(facts: list[Fact], report_dates: dict[str, str]) -> tuple[set[tuple], list[Unknown]]:
    """(excluded (document_id, key) pairs, unknowns). ``report_dates``: accession -> report date."""
    by_key: dict[tuple, list[Fact]] = {}
    for f in facts:
        by_key.setdefault(f.key, []).append(f)
    excluded = set()
    for fs in by_key.values():
        fs.sort(key=lambda f: (f.published_at, f.document_id))
        for prev, f in zip(fs, fs[1:]):
            if f.value != prev.value and out_of_period(f, report_dates.get(f.document_id, "")):
                excluded.add((f.document_id, f.key))
    unknowns = []
    if excluded:
        sample = sorted(excluded)[:5]
        unknowns.append(Unknown("suspect_values_excluded",
                                "공시의 보고 대상 기간과 맞지 않는 값이 있어 의심 값으로 보고 분석에서 제외함",
                                f"{len(excluded)} values, e.g. {sample}"))
    return excluded, unknowns


def is_recast(fact: Fact) -> bool:
    return fact.form in RECAST
