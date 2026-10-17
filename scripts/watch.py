"""Check the watchlist for a window and write a brief; optional "what if" scenario.

    python scripts/watch.py --since 2023-06-30 --until 2023-09-30
    python scripts/watch.py --until 2025-06-30 --rate-bp 100 --ebitda-pct -20
    python scripts/watch.py --state-dir watch_state     # scheduled run: since = last run

Watchlist: data/watchlist.json (list of ledger file names in data/ledger/). Writes
reports/watch_<until>.md; with --state-dir also <state-dir>/new_alerts.md and the number of
alerts to $GITHUB_OUTPUT (for the scheduled workflow).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import config, watch, watch_report  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.ledger import Ledger  # noqa: E402


def load_watchlist() -> list[Ledger]:
    names = json.loads((config.DATA_DIR / "watchlist.json").read_text(encoding="utf-8"))
    return [Ledger.load(config.DATA_DIR / "ledger" / n) for n in names]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until", default=date.today().isoformat())
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--rate-bp", type=float, default=0.0)
    ap.add_argument("--ebitda-pct", type=float, default=0.0)
    a = ap.parse_args()
    state_file = a.state_dir / "state.json" if a.state_dir else None
    since = a.since
    if since is None and state_file and state_file.exists():
        since = json.loads(state_file.read_text())["last_until"]
    since = since or (date.fromisoformat(a.until) - timedelta(days=7)).isoformat()

    ledgers = load_watchlist()
    http = Http()
    res = watch.run(ledgers, since, a.until, http)
    rows, label = None, ""
    if a.rate_bp or a.ebitda_pct:
        rows, unk = watch.scenario(ledgers, a.until, http, a.rate_bp, a.ebitda_pct)
        res.unknowns += unk
        label = f"금리 {a.rate_bp:+.0f}bp, EBITDA {a.ebitda_pct:+.0f}%"
    md = watch_report.render(res, rows, label)
    out = config.ROOT / "reports" / f"watch_{a.until}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    if a.state_dir:
        a.state_dir.mkdir(parents=True, exist_ok=True)
        important = [x for x in res.alerts if x.severity in ("high", "medium")]
        (a.state_dir / "new_alerts.md").write_text(md, encoding="utf-8")
        state_file.write_text(json.dumps({"last_until": a.until}))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write(f"alerts={len(important)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
