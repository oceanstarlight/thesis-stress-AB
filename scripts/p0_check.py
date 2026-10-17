"""P0 live check: can SEC data be rebuilt as of past dates?

    python scripts/p0_check.py AES 2023-06-30 2025-06-30

For each date it prints the latest quarterly and annual values known on that date, checks that
no later filing leaked in, counts restated periods and lists the filings published between
the dates (the replay feed). Needs SEC_USER_AGENT (name + email).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import pit  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.sources.sec import SecSource  # noqa: E402

CONCEPTS = [
    "us-gaap:Revenues",
    "us-gaap:InterestExpense",
    "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "us-gaap:LongTermDebtNoncurrent",
]
QUARTER, YEAR = (80, 100), (350, 380)


def fmt(f) -> str:
    if f is None:
        return "-"
    return f"{f.value / 1e6:,.0f}M ({f.period_start or ''}~{f.period_end}, {f.form} filed {f.published_at}, {f.document_id})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("company", help="ticker or CIK")
    ap.add_argument("dates", nargs="+", help="as-of dates, YYYY-MM-DD")
    a = ap.parse_args()

    res = SecSource(Http()).load(a.company)
    for u in res.unknowns:
        print(f"[{u.code}] {u.message} {u.detail}")
    if not res.facts:
        return 1
    print(f"\n{res.name}: {len(res.facts):,} facts, {len(res.filings):,} filings")

    keys = {f.key for f in res.facts}
    restated = [k for k in keys if pit.restatements(res.facts, k)]
    print(f"restated periods: {len(restated):,} of {len(keys):,}")
    print("most restated concepts:", Counter(k[0] for k in restated).most_common(5))

    for as_of in a.dates:
        snap = pit.snapshot(res.facts, as_of)
        print(f"\n== as of {as_of}: {len(snap.facts):,} values, leaks={len(pit.leaks(snap))}, "
              f"same-day conflicts={len(snap.unknowns)}")
        for c in CONCEPTS:
            q = snap.series(c, days=QUARTER)
            y = snap.series(c, days=YEAR)
            inst = [f for f in snap.series(c) if f.days is None]
            print(f"  {c}")
            if q or y:
                print(f"    latest quarter: {fmt(q[-1] if q else None)}")
                print(f"    latest year:    {fmt(y[-1] if y else None)}")
            else:
                print(f"    latest:         {fmt(inst[-1] if inst else None)}")

    if len(a.dates) >= 2:
        start, end = sorted(a.dates)[0], sorted(a.dates)[-1]
        between = [f for f in res.filings if start < f.filing_date <= end and f.form in ("10-K", "10-Q", "10-K/A", "10-Q/A", "8-K")]
        print(f"\n== filings published in ({start}, {end}]: {len(between)}")
        for f in between[:12]:
            print(f"  {f.filing_date} {f.accepted_at[11:19]}Z {f.form:6} {f.items:12} {f.url}")
        if len(between) > 12:
            print(f"  ... {len(between) - 12} more")

    # Show one restatement in detail as evidence.
    for k in sorted(restated, key=lambda k: k[3], reverse=True):
        if k[0] in CONCEPTS:
            print(f"\n== restatement example: {k}")
            for v in pit.versions(res.facts, k):
                print(f"  {v.published_at} {v.form:6} {v.document_id} value={v.value / 1e6:,.0f}M")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
