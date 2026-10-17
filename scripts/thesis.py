"""Build a ledger from company guidance or from an analyst memo, then audit it with scripts/audit.py.

    python scripts/thesis.py 1603145 --as-of 2023-06-30 --name XPLR            # company guidance
    python scripts/thesis.py AES --as-of 2023-06-30 --memo memo.txt --name AES_memo

Guidance: targets stated in earnings / Regulation FD releases in the 200 days up to the date.
Memo: targets in the memo text (a memo written after the date may contain hindsight; the
report says so). Writes data/ledger/<name>_<date>.json.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import config, guidance  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.ledger import Ledger  # noqa: E402
from riskprobe.sources.sec import SecSource  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("company", help="ticker or CIK")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--memo", type=Path, help="text file with the analyst's thesis")
    ap.add_argument("--name", help="ledger file name prefix (default: company)")
    a = ap.parse_args()
    src = SecSource(Http())
    data = src.load(a.company)
    if not data.filings:
        print([u.message for u in data.unknowns])
        return 1
    if a.memo:
        memo = a.memo.read_text(encoding="utf-8")
        paras = [p.strip() for p in memo.split("\n") if p.strip()]
        r = guidance.extract_targets(paras, f"사용자 메모 ({a.memo.name})", str(a.memo), a.as_of, source="user")
        targets, unknowns = r.targets, r.unknowns
        source = "user"
    else:
        targets, unknowns = guidance.latest_before(src, data.filings, a.as_of)
        source = "disclosed"
    lg = Ledger(a.company, data.name)
    for asm in guidance.to_assumptions(targets, a.as_of, threshold_source=source):
        lg.add(asm)
    path = lg.save(config.DATA_DIR / "ledger" / f"{a.name or a.company}_{a.as_of}.json")
    for asm in lg.assumptions:
        print(f"{asm.id}: {asm.statement} | 기준 {asm.threshold.value}% | {asm.source_quote[:160]}")
    for u in unknowns:
        print(f"[{u.code}] {u.message} {u.detail[:300]}")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
