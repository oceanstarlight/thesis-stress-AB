"""Replay a recorded decision (ledger) through later filings and write the audit report.

    python scripts/audit.py data/ledger/HE_2023-06-30.json --end 2025-06-30

Writes reports/audit_<ledger>_<end>.md and the ledger with its status history next to it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import audit, audit_report, config  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.ledger import Ledger  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger", type=Path)
    ap.add_argument("--end", default=date.today().isoformat())
    a = ap.parse_args()
    res = audit.run(Ledger.load(a.ledger), a.end, Http())
    md = audit_report.render(res)
    out = config.ROOT / "reports" / f"audit_{a.ledger.stem}_{a.end}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
