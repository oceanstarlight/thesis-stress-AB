"""Run Probe for one company and write the risk report and ledger.

    python scripts/probe.py AES --as-of 2025-06-30
    python scripts/probe.py AES --as-of 2025-06-30 --total-debt 28.8e9 --floating-debt 8.9e9

Writes reports/probe_<company>_<date>.md and data/ledger/<company>_<date>.json.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import config, probe, report  # noqa: E402
from riskprobe.http import Http  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("company", help="ticker or CIK")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--total-debt", type=float)
    ap.add_argument("--floating-debt", type=float)
    ap.add_argument("--coverage-floor", type=float, help="interest coverage threshold (x)")
    ap.add_argument("--leverage-cap", type=float, help="net debt / EBITDA threshold (x)")
    ap.add_argument("--no-llm-summary", action="store_true")
    a = ap.parse_args()
    user = {"total_debt": a.total_debt, "floating_debt": a.floating_debt,
            "interest_coverage": a.coverage_floor, "net_debt_to_ebitda": a.leverage_cap}
    res = probe.run(a.company, a.as_of, Http(), {k: v for k, v in user.items() if v is not None})
    md = report.render(res, use_llm=not a.no_llm_summary)
    tag = f"{a.company.upper().replace(':', '-')}_{a.as_of}"
    out = config.ROOT / "reports" / f"probe_{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    if res.ledger:
        res.ledger.save(config.DATA_DIR / "ledger" / f"{tag}.json")
    print(md)
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
