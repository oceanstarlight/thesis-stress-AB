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
            end = book.anchor()
            rs = []
            for key, suffix in (("ebitda", ""), ("ebitda_adjusted", "_adjusted")):
                e = ind.get(key)
                if e is None or e.value is None:
                    continue
                rs += [
                    reverse.ebitda_drop_to_coverage(e.value, book.ttm("interest_expense", end),
                                                    reverse.default_threshold("interest_coverage" + suffix)),
                    reverse.ebitda_drop_to_leverage(reverse.net_debt(book.at("total_debt", end), book.at("cash", end)),
                                                    e.value, reverse.default_threshold("net_debt_to_ebitda" + suffix)),
                ]
            if rs:
                for r in rs:
                    print(f"  [역산] {r.label_ko} [{'조정' if 'adjusted' in (r.threshold.note if r.threshold else '') else '공시'}]: "
                          f"{r.status} shock={show(r.shock, r.unit)} grade={r.grade or '-'}")
            for u in book.unknowns:
                print(f"  [{u.code}] {u.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
