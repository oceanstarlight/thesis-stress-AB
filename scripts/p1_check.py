"""P1 live check: indicators and reverse stress for real companies at past dates.

    python scripts/p1_check.py XPLR CCI --as-of 2023-06-30 2025-06-30

Thresholds are the default rules in config (labeled as such). Needs SEC_USER_AGENT.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import indicators, pit, quality, reverse  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.sources.sec import SecSource  # noqa: E402


def show(v: float | None, unit: str) -> str:
    if v is None:
        return "-"
    return f"{v / 1e6:,.0f}M" if unit == "USD" else f"{v:,.2f}{unit}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("companies", nargs="+")
    ap.add_argument("--as-of", nargs="+", required=True)
    a = ap.parse_args()
    src = SecSource(Http())
    for company in a.companies:
        res = src.load(company)
        if not res.facts:
            print(company, [u.message for u in res.unknowns])
            continue
        excluded, q_unknowns = quality.screen(res.facts, {f.accession: f.report_date for f in res.filings})
        print(f"\n######## {res.name} ({company}): suspect values excluded={len(excluded)}")
        for as_of in a.as_of:
            book = indicators.Book(pit.snapshot(res.facts, as_of, exclude=excluded))
            ind = indicators.compute(book)
            print(f"== as of {as_of}, indicators at {book.anchor()}")
            for i in ind.values():
                missing = "; ".join(u.detail for u in i.unknowns)
                print(f"  {i.label_ko:28} {show(i.value, i.unit):>12}  {('missing: ' + missing) if missing else ''}")
            e = ind.get("ebitda")
            if e and e.value is not None:
                end = book.anchor()
                rs = [
                    reverse.ebitda_drop_to_coverage(e.value, book.ttm("interest_expense", end),
                                                    reverse.default_threshold("interest_coverage")),
                    reverse.ebitda_drop_to_leverage(reverse.net_debt(book.at("total_debt", end), book.at("cash", end)),
                                                    e.value, reverse.default_threshold("net_debt_to_ebitda")),
                ]
                for r in rs:
                    print(f"  [역산] {r.label_ko}: {r.status} shock={show(r.shock, r.unit)} grade={r.grade or '-'} "
                          f"(기준 {r.threshold.value if r.threshold else '-'}, {r.threshold.source if r.threshold else ''})")
            for u in book.unknowns:
                print(f"  [{u.code}] {u.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
