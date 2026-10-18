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

import re
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


# Words dropped when matching company names ("Alphabet Inc." == "alphabet").
_NAME_NOISE = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc",
               "lp", "sa", "nv", "ag", "the", "adr", "de", "ma", "ny"}


def norm_name(s: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in _NAME_NOISE)


@dataclass
class Candidate:
    cik: str
    ticker: str  # first listed ticker (usually the common share)
    title: str
    tickers: list[str] = field(default_factory=list)
    market: str = "미국 SEC"

    @property
    def label(self) -> str:
        return f"{self.title} ({', '.join(self.tickers[:3])} · {self.market})"


# Sectors where the debt-service indicators (EBITDA coverage, net debt/EBITDA) do not describe risk.
# SIC 60xx-64xx: banks, credit, brokers, insurance. REITs (6798) are kept: their leverage tests apply.
FINANCIAL_SIC = (6000, 6499)
FOREIGN_FORMS = ("20-F", "40-F")


@dataclass
class Profile:
    """Light pre-check from the submissions file: who files what, and whether our indicators fit."""
    cik: str
    name: str
    sic: str = ""
    sic_description: str = ""
    annual_forms: list[str] = field(default_factory=list)
    warnings: list[Unknown] = field(default_factory=list)


def profile_warnings(sic: str, sic_description: str, forms: set[str]) -> list[Unknown]:
    out = []
    if not forms & {"10-K", "10-Q"} and forms & set(FOREIGN_FORMS):
        out.append(Unknown("sec_foreign_filer",
                           "외국 기업용 연차보고서 양식으로 공시해 분기 값이 없고 수시공시 분류가 맞지 않음. 지표 신뢰도 낮음",
                           ", ".join(sorted(forms & set(FOREIGN_FORMS)))))
    elif not forms & {"10-K", "10-Q"}:
        out.append(Unknown("sec_no_periodic", "미국 정기 재무보고서(연차·분기)가 없어 지표를 계산할 수 없음"))
    if sic.isdigit() and FINANCIAL_SIC[0] <= int(sic) <= FINANCIAL_SIC[1]:
        out.append(Unknown("sec_financial_sector",
                           f"금융업({sic_description or '은행·보험 등'})은 예금·보험부채가 차입금과 섞여 EBITDA·레버리지 지표가 위험을 설명하지 못함. 지표 신뢰도 낮음",
                           f"SIC {sic}"))
    return out


@dataclass
class Filing:
    accession: str
    form: str
    filing_date: str
    accepted_at: str  # ISO-8601 acceptance time, may be empty
    report_date: str
    items: str  # 8-K item numbers, e.g. "2.02,9.01" (DART: the SEC-equivalent item of a tagged title)
    url: str
    title: str = ""  # DART report name, e.g. "[기재정정]사업보고서 (2023.12)"


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
        self._last_submissions: dict = {}

    def available(self) -> tuple[bool, str]:
        ua = config.env("SEC_USER_AGENT")
        return (True, "") if ua and "@" in ua else (False, "연락처가 담긴 사용자 에이전트 설정이 없어 조회하지 못함")

    def _get(self, url: str):
        return self.http.get(url, headers={"User-Agent": config.env("SEC_USER_AGENT"), "Accept-Encoding": "gzip, deflate"})

    def tickers(self) -> list[dict]:
        if self._tickers is None:
            self._tickers = list(self._get(TICKERS).json().values())
        return self._tickers

    def search(self, query: str, limit: int = 10) -> list[Candidate]:
        """Ticker, CIK or company name -> ranked candidates, one per company (CIK).

        Rank: exact ticker or CIK, exact name, name starts with the query, every query word starts
        a name word, then substring. Deterministic, no network beyond the cached ticker file.
        """
        q = query.strip()
        if not q:
            return []
        qn, qu = norm_name(q), q.upper()
        qwords = qn.split()
        by_cik: dict[str, Candidate] = {}
        rank: dict[str, tuple] = {}
        for i, t in enumerate(self.tickers()):
            cik = pad(t["cik_str"])
            c = by_cik.setdefault(cik, Candidate(cik, t["ticker"], t["title"]))
            c.tickers.append(t["ticker"])
            tn = norm_name(t["title"])
            if t["ticker"].upper() == qu or (q.isdigit() and int(q) == int(t["cik_str"])):
                r = 0
            elif qn and tn == qn:
                r = 1
            elif qn and tn.startswith(qn):
                r = 2
            elif qwords and all(any(w.startswith(x) for w in tn.split()) for x in qwords):
                r = 3
            elif len(qn) >= 3 and qn.replace(" ", "") in tn.replace(" ", ""):
                r = 4
            else:
                continue
            # Ties: shorter names first (the parent over "... Capital Trust"), then file order (market cap).
            key = (r, len(tn), i)
            rank[cik] = min(rank.get(cik, key), key)
        return [by_cik[c] for c in sorted(rank, key=rank.get)][:limit]

    def cik_for(self, query: str) -> str | None:
        """Ticker, CIK or company name -> zero-padded CIK (best search match)."""
        q = query.strip()
        if q.isdigit():
            return pad(q)
        found = self.search(q, limit=1)
        return found[0].cik if found else None

    def profile(self, cik: str) -> Profile:
        d = self._get(SUBMISSIONS.format(cik=pad(cik))).json()
        forms = set(d["filings"]["recent"]["form"])
        sic, desc = str(d.get("sic") or ""), d.get("sicDescription") or ""
        return Profile(pad(cik), d.get("name", ""), sic, desc,
                       sorted(forms & {"10-K", "20-F", "40-F"}), profile_warnings(sic, desc, forms))

    def filings(self, cik: str) -> tuple[list[Filing], str]:
        d = self._get(SUBMISSIONS.format(cik=pad(cik))).json()
        pages = [d["filings"]["recent"]] + [self._get(SUBMISSIONS_PAGE.format(name=f["name"])).json()
                                            for f in d["filings"].get("files", [])]
        self._last_submissions = d
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

    def load(self, query: str, since: str | None = None) -> SecResult:
        """Facts and filings for a ticker, CIK or name. Never raises; failures become unknowns.
        ``since`` is accepted for parity with DART; companyfacts comes whole in one call."""
        res = SecResult()
        ok, reason = self.available()
        if not ok:
            res.unknowns.append(Unknown("sec_unavailable", f"{self.label_ko}: {reason}"))
            return res
        try:
            cik = self.cik_for(query)
            if cik is None:
                res.unknowns.append(Unknown("sec_not_found", "입력한 종목코드·CIK·회사 이름에 해당하는 미국 공시 기업을 찾지 못함", query))
                return res
            res.filings, res.name = self.filings(cik)
            d = self._last_submissions
            res.unknowns += profile_warnings(str(d.get("sic") or ""), d.get("sicDescription") or "",
                                             {f.form for f in res.filings})
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
