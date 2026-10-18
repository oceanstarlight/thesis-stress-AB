"""DART / OpenDART (Korea, key DART_API_KEY).

- Company list: listed companies bundled in ``data/dart_corps.json`` (scripts/build_dart_index.py),
  else the corp code file (a slow multi-megabyte download, cached for a month).
- Filing list (``list.json``): periodic reports (사업·반기·분기보고서) with receipt dates, and
  current reports (주요사항보고서, 거래소공시) tagged by title rules as timeline events.
- Financial statements per report (``fnlttSinglAcntAll.json``): face statements only.

Point in time (fast mode, decided with the user): the per-report API returns the latest amended
version of a report and names that version's receipt number. Its values are therefore dated at
that receipt date, never at the original report's date, so nothing from the future leaks in;
the values the original report showed are not available (a gap until the amendment date).

Face statements carry no total-borrowings line and often no depreciation line, so three
concepts are summed here from the lines that are present, with the parts kept in the detail:
``dart-calc:TotalBorrowings`` (borrowings, bonds and lease liabilities, as Korean rating
agencies count debt after IFRS 16), ``dart-calc:DepreciationAndAmortisation`` (cash flow
add-backs) and ``dart-calc:InterestPaid`` (cash interest, used only when no interest expense
line exists). When depreciation is missing, the indicator catalog falls back to operating
income (EBIT) and says so.
"""

from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

from riskprobe import config
from riskprobe.models import Fact, Unknown
from riskprobe.sources.sec import Candidate, Filing, SecResult

API = "https://opendart.fss.or.kr/api"
VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
KR_PREFIX = "KR:"
KINDS = ("사업보고서", "반기보고서", "분기보고서")
_KIND = re.compile(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")

# Borrowing lines summed into total borrowings. Generic totals are used only when no
# component line is present, so a statement that shows both is not double counted.
BORROWING_PARTS = {
    "ifrs-full_ShorttermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "ifrs-full_LongtermBorrowings",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_CurrentPortionOfNoncurrentBondsIssued", "ifrs-full_CurrentBondsIssued", "ifrs-full_NoncurrentBondsIssued",
    "ifrs-full_BondsIssued", "dart_ShortTermBorrowings", "dart_LongTermBorrowingsGross", "dart_BondsIssued",
    "dart_CurrentPortionOfBonds", "dart_CurrentPortionOfLongTermBorrowings",
    "ifrs-full_CurrentLeaseLiabilities", "ifrs-full_NoncurrentLeaseLiabilities",
}
BORROWING_TOTALS = {"ifrs-full_Borrowings", "ifrs-full_CurrentBorrowings", "ifrs-full_NoncurrentBorrowings",
                    "ifrs-full_LeaseLiabilities"}
# Lines are also matched by their Korean name: ids vary by company and year (Samsung's
# 단기차입금 has no standard id, Korean Air's 자산유동화차입금 neither, DART's own lease ids
# are spelled inconsistently).
BORROWING_NAME = re.compile(r"(차입금|사채|리스부채|장기부채)$")
BORROWING_NAME_EXCLUDE = re.compile(r"채권|자산$|할인|상환할증")
DA_IDS = {"ifrs-full_AdjustmentsForDepreciationExpense", "ifrs-full_AdjustmentsForAmortisationExpense",
          "dart_AdjustmentsForDepreciationExpense", "dart_AdjustmentsForAmortisationExpense",
          "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",
          "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"}
DA_NAME = re.compile(r"^(유형자산)?감가상각비$|^무형자산상각비$|^사용권자산(감가)?상각비$|^감가상각비및무형자산상각비$")
INTEREST_PAID_IDS = {"ifrs-full_InterestPaidClassifiedAsOperatingActivities",
                     "ifrs-full_InterestPaidClassifiedAsFinancingActivities"}

# Current-report title rules: (pattern on the title without spaces, SEC-equivalent item or "",
# label, severity). The item lets the lifecycle hard rules (bankruptcy, acceleration) apply.
EVENT_RULES = [
    (r"회생절차|파산|부도발생|은행거래정지|해산사유", "1.03", "파산·회생·부도", "high"),
    (r"채권은행등의관리절차|관리절차개시|기업구조개선|워크아웃", "1.03", "채권단 관리절차", "high"),
    (r"기한의이익상실", "2.04", "기한의 이익 상실(조기상환 사유)", "high"),
    (r"상장폐지|관리종목|매매거래정지|상장적격성", "3.01", "상장폐지·관리종목·거래정지", "high"),
    (r"감사의견(거절|부적정|한정)|의견거절|부적정의견|한정의견", "", "감사의견 비적정", "high"),
    (r"횡령|배임", "", "횡령·배임", "high"),
    (r"영업정지", "", "영업정지", "high"),
    (r"재해발생", "", "재해·사고", "high"),
    (r"소송등의제기|소송등의판결|소송", "", "소송", "medium"),
    (r"감자결정", "", "감자", "medium"),
    (r"채무인수|채무보증", "", "채무 인수·보증", "info"),  # routine for groups guaranteeing subsidiaries
    (r"유상증자결정|전환사채권발행결정|신주인수권부사채권발행결정|교환사채권발행결정|자본으로인정되는채무증권발행결정",
     "", "증자·사채 발행", "info"),
    (r"합병|분할|영업양수|영업양도|유형자산양수|유형자산양도|주식교환|주식이전|타법인주식및출자증권(양수|양도)",
     "", "합병·분할·양수도", "info"),
]
_EVENT_RULES = [(re.compile(p), item, label, sev) for p, item, label, sev in EVENT_RULES]
FINANCIAL_KSIC = ("64", "65", "66")  # 금융업, 보험·연금업, 금융·보험 관련 서비스업


def tag_title(title: str) -> tuple[str, str, str] | None:
    """(item, label, severity) for a current-report title, or None when no rule matches."""
    t = re.sub(r"\s+", "", title)
    for pat, item, label, sev in _EVENT_RULES:
        if pat.search(t):
            return item, label, sev
    return None


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\(주\)|㈜|주식회사|\bco\b|\bltd\b|\binc\b|\bcorp(oration)?\b|\bcompany\b|\blimited\b", " ", s)
    return re.sub(r"[^0-9a-z가-힣]+", "", s)


def is_query(query: str) -> bool:
    q = query.strip()
    return q.upper().startswith(KR_PREFIX) or bool(re.search(r"[가-힣]", q))


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _shift(y: int, m: int, k: int) -> tuple[int, int]:
    y2, m0 = divmod(y * 12 + (m - 1) + k, 12)
    return y2, m0 + 1


def _month_end(y: int, m: int) -> str:
    ny, nm = _shift(y, m, 1)
    return (date(ny, nm, 1) - timedelta(days=1)).isoformat()


def _amount(s) -> float | None:
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Report:
    """One periodic report and its amendments."""
    kind: str
    year: int
    month: int  # period end month
    filings: list[Filing] = field(default_factory=list)  # original first, then amendments

    @property
    def end(self) -> str:
        return _month_end(self.year, self.month)


class DartSource:
    name = "dart"
    label_ko = "DART"

    def __init__(self, http):
        self.http = http
        self._corps: list[dict] | None = None

    def available(self) -> tuple[bool, str]:
        return (True, "") if config.env("DART_API_KEY") else (False, "API 키가 없어 한국 공시를 조회하지 못함")

    def _get(self, path: str, ttl_hours: float | None = None, **params):
        return self.http.get(f"{API}/{path}", params={"crtfc_key": config.env("DART_API_KEY"), **params},
                             ttl_hours=ttl_hours)

    # ----------------------------------------------------------------- companies
    def corps(self) -> list[dict]:
        if self._corps is None:
            if config.DART_INDEX.exists():
                import json
                self._corps = json.loads(config.DART_INDEX.read_text(encoding="utf-8"))
            else:
                r = self._get("corpCode.xml", ttl_hours=config.DART_CORPCODE_TTL_HOURS)
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    root = ET.fromstring(zf.read(zf.namelist()[0]))
                self._corps = [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("list")]
                self._corps = [c for c in self._corps if c.get("stock_code")]
        return self._corps

    def search(self, query: str, limit: int = 10) -> list[Candidate]:
        """Name (Korean or English), 6-digit stock code or 8-digit corp code -> listed companies."""
        q = query.strip()
        if q.upper().startswith(KR_PREFIX):
            q = q[len(KR_PREFIX):].strip()
        if not q:
            return []
        qn = norm_name(q)
        ranked = []
        for i, c in enumerate(self.corps()):
            names = [norm_name(c.get("corp_name", "")), norm_name(c.get("corp_eng_name", ""))]
            if q in (c.get("stock_code"), c.get("corp_code")):
                r = 0
            elif qn and qn in names:
                r = 1
            elif qn and any(n.startswith(qn) for n in names if n):
                r = 2
            elif len(qn) >= 2 and qn in names[0]:  # substring on the Korean name only (English is noisy)
                r = 3
            else:
                continue
            ranked.append(((r, len(names[0]), i), c))
        ranked.sort(key=lambda x: x[0])
        return [Candidate(f"{KR_PREFIX}{c['stock_code']}", c["stock_code"], c["corp_name"], [c["stock_code"]], "한국 DART")
                for _, c in ranked[:limit]]

    def corp_for(self, query: str) -> dict | None:
        q = query.strip()
        if q.upper().startswith(KR_PREFIX):
            q = q[len(KR_PREFIX):].strip()
        found = self.search(q, limit=1)
        if not found:
            return None
        return next(c for c in self.corps() if c.get("stock_code") == found[0].ticker)

    def company(self, corp_code: str) -> dict:
        return self._get("company.json", ttl_hours=24 * 7, corp_code=corp_code).json()

    def profile_warnings(self, company: dict) -> list[Unknown]:
        code = str(company.get("induty_code") or "")
        if code.startswith(FINANCIAL_KSIC):
            return [Unknown("dart_financial_sector", "금융업(은행·보험·증권 등)은 예금·보험부채가 차입금과 섞여 "
                            "EBITDA·레버리지 지표가 위험을 설명하지 못함. 지표 신뢰도 낮음", f"KSIC {code}")]
        return []

    # ------------------------------------------------------------------ filings
    def _list(self, corp_code: str, ty: str, bgn: str, max_pages: int = 10) -> list[dict]:
        out, page = [], 1
        while page <= max_pages:
            d = self._get("list.json", ttl_hours=12, corp_code=corp_code, bgn_de=bgn, end_de=date.today().strftime("%Y%m%d"),
                          pblntf_ty=ty, page_no=page, page_count=100).json()
            if d.get("status") == "013":  # no filings
                break
            if d.get("status") != "000":
                raise ValueError(f"list.json {d.get('status')}: {d.get('message')}")
            out += d.get("list", [])
            if page >= int(d.get("total_page", 1)):
                break
            page += 1
        return out

    def reports(self, rows: list[dict]) -> list[Report]:
        groups: dict[tuple, Report] = {}
        for x in sorted(rows, key=lambda x: x["rcept_no"]):
            m = _KIND.search(x["report_nm"])
            if not m:
                continue
            kind, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
            amended = x["report_nm"].strip().startswith("[")
            rep = groups.setdefault((kind, y, mo), Report(kind, y, mo))
            rep.filings.append(Filing(x["rcept_no"], kind + ("/A" if amended else ""), _iso(x["rcept_dt"]), "",
                                      _month_end(y, mo), "", VIEWER.format(rcept_no=x["rcept_no"]), x["report_nm"]))
        for rep in groups.values():  # original first when one exists
            rep.filings.sort(key=lambda f: (f.form.endswith("/A"), f.accession))
        return sorted(groups.values(), key=lambda r: r.end)

    def events(self, corp_code: str, bgn: str) -> list[Filing]:
        out = []
        for ty, form in (("B", "주요사항보고서"), ("I", "거래소공시")):
            for x in self._list(corp_code, ty, bgn):
                tagged = tag_title(x["report_nm"])
                if x["report_nm"].strip().startswith("["):  # amendment of an event already listed
                    continue
                if tagged is None or (ty == "I" and tagged[2] == "info"):
                    continue
                out.append(Filing(x["rcept_no"], form, _iso(x["rcept_dt"]), "", "", tagged[0],
                                  VIEWER.format(rcept_no=x["rcept_no"]), x["report_nm"]))
        return out

    # ---------------------------------------------------------------- financials
    def _statement(self, corp_code: str, rep: Report, acc_mt: int, fs_div: str) -> tuple[dict, int]:
        months_into = (rep.month - acc_mt) % 12 or 12
        code = {"사업보고서": "11011", "반기보고서": "11012"}.get(rep.kind) or {3: "11013", 9: "11014"}.get(months_into)
        if code is None:
            return {"status": "skip"}, months_into
        fy_end_year = _shift(rep.year, rep.month, 12 - months_into)[0]
        wanted = {f.accession for f in rep.filings}
        d: dict = {}
        for bsns_year in dict.fromkeys((fy_end_year, rep.year, fy_end_year - 1)):
            d = self._get("fnlttSinglAcntAll.json", ttl_hours=config.DART_FINANCIAL_TTL_HOURS, corp_code=corp_code,
                          bsns_year=str(bsns_year), reprt_code=code, fs_div=fs_div).json()
            if d.get("status") == "000" and d.get("list") and d["list"][0]["rcept_no"] in wanted:
                return d, months_into
        return ({"status": d.get("status", "?"), "message": d.get("message", "")} if d.get("status") != "000"
                else {"status": "mismatch"}), months_into

    def facts_for(self, rep: Report, d: dict, months_into: int) -> list[Fact]:
        rows = d["list"]
        rcept_no = rows[0]["rcept_no"]
        original = rep.filings[0]
        form = rep.kind + ("" if rcept_no == original.accession and not original.form.endswith("/A") else "/A")
        published = _iso(rcept_no[:8])
        url = VIEWER.format(rcept_no=rcept_no)
        end = rep.end
        fy_start = date(*_shift(rep.year, rep.month, 1 - months_into), 1).isoformat()
        q_start = date(*_shift(rep.year, rep.month, -2), 1).isoformat()
        py = lambda d_: (date.fromisoformat(d_).replace(year=int(d_[:4]) - 1)).isoformat()  # noqa: E731
        prior_end = _month_end(*_shift(rep.year, rep.month, -12))
        prior_fy_end = _month_end(*_shift(rep.year, rep.month, -months_into))
        annual = rep.kind == "사업보고서"

        out: dict[tuple, Fact] = {}

        def add(concept: str, unit: str, start: str | None, end_: str, v: float | None) -> None:
            if v is None:
                return
            f = Fact(concept, unit, start, end_, v, published, rcept_no, form, "dart", url)
            out.setdefault(f.key, f)

        sums: dict[tuple, dict[str, float]] = {}  # (concept, start, end) -> {part label: value}

        def part(concept: str, start: str | None, end_: str, label: str, v: float | None) -> None:
            if v is not None:
                p = sums.setdefault((concept, start, end_), {})
                p[label] = p.get(label, 0.0) + v

        for x in rows:
            aid, nm, sj = x["account_id"], re.sub(r"\s+", "", x.get("account_nm", "")), x["sj_div"]
            unit = x.get("currency") or "KRW"
            std = aid.startswith(("ifrs-full_", "dart_"))
            concept = aid.replace("_", ":", 1) if std else None
            cur, prev = _amount(x.get("thstrm_amount")), _amount(x.get("frmtrm_amount"))
            if sj == "BS":
                periods = [(None, end, cur), (None, prior_fy_end if not annual else prior_end, prev)]
            elif sj in ("IS", "CIS"):
                if annual:
                    periods = [(fy_start, end, cur), (py(fy_start), prior_end, prev)]
                else:
                    periods = [(q_start, end, cur), (fy_start, end, _amount(x.get("thstrm_add_amount"))),
                               (py(q_start), prior_end, _amount(x.get("frmtrm_q_amount"))),
                               (py(fy_start), prior_end, _amount(x.get("frmtrm_add_amount")))]
            elif sj == "CF":
                periods = [(fy_start, end, cur), (py(fy_start), prior_end, prev)]
            else:
                continue
            for start, e, v in periods:
                if concept:
                    add(concept, unit, start, e, v)
                if sj == "BS" and (aid in BORROWING_PARTS or (BORROWING_NAME.search(nm) and not BORROWING_NAME_EXCLUDE.search(nm))):
                    part("dart-calc:TotalBorrowings", start, e, nm, v)
                if sj == "BS" and aid in BORROWING_TOTALS:
                    part("dart-calc:TotalBorrowingsFromTotals", start, e, nm, v)
                if sj == "CF" and (aid in DA_IDS or DA_NAME.match(nm)):
                    part("dart-calc:DepreciationAndAmortisation", start, e, nm, v)
                if sj == "CF" and aid in INTEREST_PAID_IDS:
                    part("dart-calc:InterestPaid", start, e, nm, v)
        unit = rows[0].get("currency") or "KRW"
        for (concept, start, e), parts in sums.items():
            if concept == "dart-calc:TotalBorrowingsFromTotals":
                if ("dart-calc:TotalBorrowings", start, e) in sums:
                    continue
                concept = "dart-calc:TotalBorrowings"
            add(concept, unit, start, e, sum(parts.values()))
        return list(out.values())

    # --------------------------------------------------------------------- load
    def load(self, query: str, since: str | None = None) -> SecResult:
        """Facts and filings for a Korean listed company. Never raises; failures become unknowns.
        ``since``: only reports for periods ending on or after this date are fetched."""
        res = SecResult()
        ok, reason = self.available()
        if not ok:
            res.unknowns.append(Unknown("dart_unavailable", f"{self.label_ko}: {reason}"))
            return res
        try:
            corp = self.corp_for(query)
            if corp is None:
                res.unknowns.append(Unknown("dart_not_found", "입력한 회사 이름·종목코드에 해당하는 한국 상장사를 찾지 못함", query))
                return res
            comp = self.company(corp["corp_code"])
            res.name = comp.get("corp_name") or corp["corp_name"]
            res.unknowns += self.profile_warnings(comp)
            acc_mt = int(comp.get("acc_mt") or 12)
            since = since or (date.today() - timedelta(days=365 * (config.DART_YEARS_BEFORE + 1))).isoformat()
            bgn = f"{int(since[:4]) - 1}0101"
            reps = self.reports(self._list(corp["corp_code"], "A", bgn))
            res.filings = sorted([f for r in reps for f in r.filings] + self.events(corp["corp_code"], bgn),
                                 key=lambda f: (f.filing_date, f.accession))
            reps = [r for r in reps if r.end >= since]
            if not reps:
                res.unknowns.append(Unknown("dart_no_reports", "기간 안에 제출된 정기보고서가 없어 재무 값을 만들지 못함"))
                return res
            fs_div = "CFS"
            probe_d, _ = self._statement(corp["corp_code"], reps[-1], acc_mt, "CFS")
            if probe_d.get("status") != "000":
                fs_div = "OFS"
                res.unknowns.append(Unknown("dart_separate_only", "연결재무제표가 없어 별도재무제표로 분석함"))
            with ThreadPoolExecutor(config.DART_WORKERS) as ex:
                results = list(ex.map(lambda r: (r, *self._statement(corp["corp_code"], r, acc_mt, fs_div)), reps))
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}".replace(config.env("DART_API_KEY") or "\0", "***")
            res.unknowns.append(Unknown("dart_error", f"{self.label_ko} 호출 실패, 이 구간은 확인하지 못함", msg[:200]))
            return res
        missing, amended = [], []
        for rep, d, months_into in results:
            if d.get("status") != "000":
                missing.append(f"{rep.kind} {rep.end}: {d.get('status')}")
                continue
            facts = self.facts_for(rep, d, months_into)
            res.facts += facts
            if facts and facts[0].form.endswith("/A"):
                amended.append(f"{rep.kind} {rep.end} -> {facts[0].published_at}")
        if missing:
            res.unknowns.append(Unknown("dart_report_missing", "일부 정기보고서의 재무제표를 받지 못해 그 기간 값이 없음",
                                        "; ".join(missing)[:500]))
        if amended:
            res.unknowns.append(Unknown("dart_amended_dating", "정정된 보고서는 정정 후 값만 제공돼 정정일에 공개된 값으로 처리함. "
                                        "정정 전 원래 값과 그 사이 기간은 쓸 수 없음", "; ".join(amended)[:500]))
        res.unknowns.append(Unknown("dart_face_statements", "재무제표 본문 값만 사용함. 주석에만 있는 감가상각비·차입금은 반영되지 않을 수 있음"))
        res.unknowns.append(Unknown("dart_debt_definition", "총차입금은 본문의 차입금·사채·리스부채를 더한 값(국내 신용평가 관행)"))
        return res
