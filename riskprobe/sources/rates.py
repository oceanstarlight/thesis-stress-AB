"""Public interest rate series for Watch (no key).

- SOFR, Federal Reserve Bank of New York reference rates API. Floating-rate corporate debt
  mostly resets off SOFR, so a SOFR move is the rate shock that reaches interest expense.
- 10-year Treasury constant maturity, Federal Reserve Board H.15 (Data Download Program):
  the refinancing environment for fixed-rate debt.
Each value is published on (or the business day after) its date, so a series cut at date T
is point-in-time.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from riskprobe.models import Unknown

SOFR = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
H15 = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series=bf17364827e38702b42a58cf8eaa3f78"
       "&lastobs=&from={frm}&to={to}&filetype=csv&label=include&layout=seriescolumn&type=package")
H15_COLUMN = "RIFLGFCY10_N.B"
LABELS = {"sofr": "SOFR (뉴욕 연준)", "ust10y": "미 국채 10년물 (연준 H.15)"}


@dataclass
class Series:
    key: str
    points: list[tuple[str, float]] = field(default_factory=list)  # (date, percent), ascending
    url: str = ""

    def at(self, d: str) -> tuple[str, float] | None:
        """Latest observation on or before ``d``."""
        prior = [p for p in self.points if p[0] <= d]
        return prior[-1] if prior else None

    def change_bp(self, start: str, end: str) -> tuple[float, str, str] | None:
        a, b = self.at(start), self.at(end)
        if a is None or b is None:
            return None
        return (b[1] - a[1]) * 100, a[0], b[0]


def _us(d: str) -> str:
    y, m, dd = d.split("-")
    return f"{m}/{dd}/{y}"


def _parse_h15(body: str) -> list[tuple[str, float]] | None:
    rows = list(csv.reader(io.StringIO(body)))
    head = next((i for i, row in enumerate(rows) if row and row[0] == "Time Period"), None)
    if head is None or H15_COLUMN not in rows[head]:
        return None
    col = rows[head].index(H15_COLUMN)
    pts = []
    for row in rows[head + 1:]:
        try:
            pts.append((row[0], float(row[col])))
        except (ValueError, IndexError):
            continue  # "ND" = no data (holiday)
    return sorted(pts)


def fetch(http, key: str, start: str, end: str) -> tuple[Series | None, list[Unknown]]:
    try:
        if key == "sofr":
            r = http.get(SOFR, params={"startDate": start, "endDate": end}, ttl_hours=6)
            pts = sorted((x["effectiveDate"], float(x["percentRate"])) for x in r.json().get("refRates", []))
            return Series(key, pts, r.url), []
        if key == "ust10y":
            url = H15.format(frm=_us(start), to=_us(end))
            pts = _parse_h15(http.get(url, ttl_hours=6).text)
            for _ in range(2):  # the site sometimes answers an empty 200; retry uncached
                if pts is not None:
                    break
                pts = _parse_h15(http.get(url, ttl_hours=0).text)
            if pts is None:
                raise ValueError("H.15 response without a data table")
            return Series(key, pts, url.split("&from")[0]), []
    except Exception as exc:  # noqa: BLE001
        return None, [Unknown("rates_unavailable", f"{LABELS.get(key, key)} 금리를 받지 못해 금리 트리거를 확인하지 못함",
                              f"{type(exc).__name__}: {exc}"[:200])]
    raise ValueError(key)
