"""One input, one output: lifecycle review of a decision (Probe + replay + Watch rates + verdict).

    python scripts/review.py HE --t0 2023-06-30 --end 2025-06-30
    python scripts/review.py 1603145 --t0 2023-06-30 --end 2025-06-30 --guidance
    python scripts/review.py AMT --t0 2025-06-30          # check date = T0: pre-investment review

Writes reports/review_<company>_<t0>_<end>.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import config, lifecycle, lifecycle_report  # noqa: E402
from riskprobe.http import Http  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    ap.add_argument("--t0", required=True, help="decision date")
    ap.add_argument("--end", help="check date (default: T0)")
    ap.add_argument("--guidance", action="store_true", help="add the company's own guidance as assumptions")
    ap.add_argument("--rate-bp", type=float, default=100.0)
    ap.add_argument("--ebitda-pct", type=float, default=-20.0)
    a = ap.parse_args()
    end = a.end or a.t0
    res = lifecycle.run(a.company, a.t0, end, Http(), include_guidance=a.guidance, rate_bp=a.rate_bp, ebitda_pct=a.ebitda_pct)
    md = lifecycle_report.render(res)
    out = config.ROOT / "reports" / f"review_{a.company.upper()}_{a.t0}_{end}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
