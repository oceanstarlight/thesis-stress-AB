"""Build data/dart_corps.json: listed Korean companies from DART's corp code file.

    python scripts/build_dart_index.py [--xml CORPCODE.xml]

The full corp code file is a slow multi-megabyte download; the bundled list (listed companies
only) makes Korean name search instant. Re-run occasionally for new listings.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riskprobe import config  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.sources import dart  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", help="already downloaded CORPCODE.xml (skips the download)")
    args = ap.parse_args()
    if args.xml:
        raw = Path(args.xml).read_bytes()
    else:
        r = dart.DartSource(Http())._get("corpCode.xml", ttl_hours=config.DART_CORPCODE_TTL_HOURS)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            raw = zf.read(zf.namelist()[0])
    rows = [{c.tag: (c.text or "").strip() for c in item} for item in ET.fromstring(raw).iter("list")]
    keep = ("corp_code", "corp_name", "corp_eng_name", "stock_code")
    listed = sorted(({k: r.get(k, "") for k in keep} for r in rows if r.get("stock_code")), key=lambda r: r["stock_code"])
    config.DART_INDEX.write_text(json.dumps(listed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(listed)} listed companies -> {config.DART_INDEX}")


if __name__ == "__main__":
    main()
