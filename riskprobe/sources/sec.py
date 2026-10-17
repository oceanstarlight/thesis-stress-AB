"""SEC EDGAR (no key; a contact User-Agent is required).

- company_tickers.json: ticker -> CIK
- submissions: filing list with filing date and acceptance time per accession number
- companyfacts: every XBRL value as reported in each filing, with ``filed`` and ``accn``.
  The same period appears once per filing that reported it, so restatements are visible.

Known limits (also returned as ``Unknown``): companyfacts starts with XBRL-era filings, and
earnings press releases (8-K Item 2.02 exhibits) are not tagged, so a number can be public
some days before the filing date seen here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riskprobe import config
from riskprobe.models import Fact, Unknown

TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_PAGE = "https://data.sec.gov/submissions/{name}"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FILING_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
PRIMARY_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


def pad(cik: str | int) -> str:
    return str(int(cik)).zfill(10)


@dataclass
class Filing:
    accession: str
    form: str
    filing_date: str
    accepted_at: str  # ISO-8601 acceptance time, may be empty
    report_date: str
    items: str  # 8-K item numbers, e.g. "2.02,9.01"
    url: str


@dataclass
class SecResult:
    facts: list[Fact] = field(default_factory=list)
    filings: list[Filing] = field(default_factory=list)
    name: str = ""
    unknowns: list[Unknown] = field(default_factory=list)


class SecSource:
    name = "sec"
    label_ko = "SEC EDGAR"

    def __init__(self, http):
        self.http = http
        self._tickers: list[dict] | None = None

    def available(self) -> tuple[bool, str]:
        ua = config.env("SEC_USER_AGENT")
        return (True, "") if ua and "@" in ua else (False, "연락처가 담긴 사용자 에이전트 설정이 없어 조회하지 못함")

    def _get(self, url: str):
        return self.http.get(url, headers={"User-Agent": config.env("SEC_USER_AGENT"), "Accept-Encoding": "gzip, deflate"})

    def tickers(self) -> list[dict]:
        if self._tickers is None:
            self._tickers = list(self._get(TICKERS).json().values())
        return self._tickers

    def cik_for(self, query: str) -> str | None:
        """Ticker or CIK -> zero-padded CIK."""
        q = query.strip()
        if q.isdigit():
            return pad(q)
        for t in self.tickers():
            if t["ticker"].upper() == q.upper():
                return pad(t["cik_str"])
        return None

    def filings(self, cik: str) -> tuple[list[Filing], str]:
        d = self._get(SUBMISSIONS.format(cik=pad(cik))).json()
        pages = [d["filings"]["recent"]] + [self._get(SUBMISSIONS_PAGE.format(name=f["name"])).json()
                                            for f in d["filings"].get("files", [])]
        out = []
        for p in pages:
            for i, acc in enumerate(p["accessionNumber"]):
                doc = p["primaryDocument"][i]
                out.append(Filing(acc, p["form"][i], p["filingDate"][i], p.get("acceptanceDateTime", [""] * (i + 1))[i],
                                  p.get("reportDate", [""] * (i + 1))[i], p.get("items", [""] * (i + 1))[i],
                                  PRIMARY_DOC.format(cik=int(cik), acc=acc.replace("-", ""), doc=doc) if doc
                                  else FILING_INDEX.format(cik=int(cik), acc=acc.replace("-", ""))))
        return sorted(out, key=lambda f: (f.filing_date, f.accession)), d.get("name", "")

    def facts(self, cik: str) -> tuple[list[Fact], str]:
        d = self._get(COMPANY_FACTS.format(cik=pad(cik))).json()
        out = []
        for taxonomy, concepts in d.get("facts", {}).items():
            for concept, body in concepts.items():
                for unit, rows in body.get("units", {}).items():
                    for r in rows:
                        acc = r["accn"]
                        out.append(Fact(f"{taxonomy}:{concept}", unit, r.get("start"), r["end"], float(r["val"]),
                                        r["filed"], acc, r.get("form", ""), "sec",
                                        FILING_INDEX.format(cik=int(cik), acc=acc.replace("-", ""))))
        return out, d.get("entityName", "")

    def load(self, query: str) -> SecResult:
        """Facts and filings for a ticker or CIK. Never raises; failures become unknowns."""
        res = SecResult()
        ok, reason = self.available()
        if not ok:
            res.unknowns.append(Unknown("sec_unavailable", f"{self.label_ko}: {reason}"))
            return res
        try:
            cik = self.cik_for(query)
            if cik is None:
                res.unknowns.append(Unknown("sec_not_found", "입력한 종목코드나 CIK에 해당하는 기업을 찾지 못함", query))
                return res
            res.filings, res.name = self.filings(cik)
            res.facts, _ = self.facts(cik)
        except Exception as exc:  # noqa: BLE001
            res.unknowns.append(Unknown("sec_error", f"{self.label_ko} 호출 실패, 이 구간은 확인하지 못함",
                                        f"{type(exc).__name__}: {exc}"[:200]))
            return res
        res.unknowns.append(Unknown(
            "sec_press_release_gap", "실적 보도자료 숫자는 구조화 데이터에 없어 실제 최초 공개일이 공시일보다 빠를 수 있음"))
        if res.facts:
            first = min(f.published_at for f in res.facts)
            res.unknowns.append(Unknown("sec_coverage_start", "구조화 재무 데이터가 시작되기 전 기간은 기준일 분석에 쓸 수 없음",
                                        f"first filed: {first}"))
        return res
