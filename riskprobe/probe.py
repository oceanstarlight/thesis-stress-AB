"""Probe (PLANS.md 7.1): where would "this investment is safe" break, and on what evidence?

Steps, all deterministic except the one extraction call:
1. Point-in-time data as of the decision date: SEC facts screened for quality, indicators.
2. Latest annual report filed by that date: keyword-selected paragraphs -> LLM extraction ->
   code verification (risk items, floating debt, rate sensitivity, covenants, customers).
3. Risk paths from code templates, solved for the shock that breaks each threshold, on
   reported and impairment-adjusted EBITDA. Thresholds: user input, else default rule; a
   disclosed covenant is computed as its own labeled scenario because its definition rarely
   matches the indicator computed here.
4. Counter-evidence: indicator rules, one-year trends, recent 8-Ks and stress-related filing
   text that argue against a comfortable conclusion (``counter``).
5. Assumptions written to a ledger for Watch and Audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riskprobe import config, counter, events, extract, indicators, pit, quality, reverse, text
from riskprobe.ledger import Assumption, Ledger, Threshold
from riskprobe.models import Evidence, Unknown
from riskprobe.sources.sec import Filing, SecSource

ANNUAL = ("10-K", "10-K/A", "20-F", "40-F")


@dataclass
class Scenario:
    """One reverse-stress result with the context needed to show it."""
    result: reverse.ReverseResult
    ebitda_basis: str  # 공시 EBITDA | 조정 EBITDA
    threshold_label: str  # 기본 규칙 | 사용자 입력 | 공시 약정 (정의 차이 주의)
    input_notes: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    query: str
    as_of: str
    name: str = ""
    anchor: str | None = None
    indicators: dict[str, indicators.Indicator] = field(default_factory=dict)
    filing: Filing | None = None
    extraction: extract.ExtractionResult | None = None
    scenarios: list[Scenario] = field(default_factory=list)
    counters: list[counter.Counter] = field(default_factory=list)
    ledger: Ledger | None = None
    unknowns: list[Unknown] = field(default_factory=list)


def _latest_annual(filings: list[Filing], as_of: str) -> Filing | None:
    """Latest original annual report; an amendment (often Part III only) is used only when no
    original was filed for that fiscal year."""
    annual = [f for f in filings if f.form in ANNUAL and f.filing_date <= as_of]
    if not annual:
        return None
    last_period = annual[-1].report_date
    originals = [f for f in annual if not f.form.endswith("/A") and f.report_date == last_period]
    return originals[-1] if originals else annual[-1]


def _floating_amount(ex: extract.ExtractionResult | None, total_debt: float | None,
                     user_floating: float | None) -> tuple[float | None, list[str], list[Evidence]]:
    """Floating-rate debt (or its equivalent) for the rate path, with how it was obtained."""
    if user_floating is not None:
        return user_floating, ["변동금리 차입금: 사용자 입력"], []
    if ex is None:
        return None, [], []
    for v in ex.of("floating_debt"):
        if "amount" in v.values:
            return v.values["amount"], ["변동금리 차입금: 연차보고서 공시 금액"], [v.evidence]
    for v in ex.of("rate_sensitivity"):
        if "interest" in v.item.measure.lower():
            eq = v.values["impact"] / (v.values["bp"] / 10_000)
            return eq, ["변동금리 차입금 환산: 공시 금리 민감도(이자비용 변화 ÷ 금리 변화)"], [v.evidence]
    for v in ex.of("floating_debt"):
        if "share_pct" in v.values and total_debt is not None:
            return v.values["share_pct"] / 100 * total_debt, ["변동금리 차입금: 공시 비중 × 총차입금"], [v.evidence]
    return None, [], []


def run(query: str, as_of: str, http, user: dict | None = None) -> ProbeResult:
    """``user`` may hold: floating_debt, total_debt (USD), interest_coverage, net_debt_to_ebitda
    (threshold values chosen by the analyst)."""
    user = user or {}
    out = ProbeResult(query, as_of)
    src = SecSource(http)
    data = src.load(query)
    out.unknowns += data.unknowns
    out.name = data.name
    if not data.facts:
        return out

    excluded, q_unknowns = quality.screen(data.facts, {f.accession: f.report_date for f in data.filings})
    out.unknowns += q_unknowns
    snap = pit.snapshot(data.facts, as_of, exclude=excluded)
    out.unknowns += snap.unknowns
    book = indicators.Book(snap)
    out.anchor = book.anchor()
    out.indicators = indicators.compute(book)
    out.unknowns += book.unknowns
    if out.anchor is None:
        out.unknowns.append(Unknown("probe_no_data", "기준일까지 공개된 재무 값이 없어 분석하지 않음"))
        return out
    end = out.anchor

    out.filing = _latest_annual(data.filings, as_of)
    if out.filing is None:
        out.unknowns.append(Unknown("probe_no_annual_report", "기준일까지 제출된 연차보고서가 없어 문서 기반 위험 요인을 쓰지 않음"))
    else:
        try:
            paras = text.select(text.paragraphs(src._get(out.filing.url).text), config.EXTRACT_MAX_CHARS)
            out.extraction = extract.extract(paras, f"{data.name} {out.filing.form} ({out.filing.filing_date})",
                                             out.filing.url, out.filing.filing_date)
            out.unknowns += out.extraction.unknowns
        except Exception as exc:  # noqa: BLE001
            out.unknowns.append(Unknown("probe_filing_error", "연차보고서 원문을 읽지 못해 문서 기반 위험 요인을 쓰지 않음",
                                        f"{type(exc).__name__}: {exc}"[:200]))

    interest = book.ttm("interest_expense", end)
    debt = book.at("total_debt", end)
    debt_note = []
    if debt is None and user.get("total_debt") is not None:
        debt = indicators.Measured(user["total_debt"], None, end, [], "user")
        debt_note = ["총차입금: 사용자 입력"]
    elif debt is None and out.extraction is not None:
        for v in out.extraction.of("floating_debt"):
            if "total_debt" in v.values:
                debt = indicators.Measured(v.values["total_debt"], None, end, [], "disclosed_text")
                debt_note = [f"총차입금: 연차보고서 문장의 금액({v.item.as_of_text or '회계연도 말'} 기준, 재무 기준 기간과 다를 수 있음)"]
                break
    nd = reverse.net_debt(debt, book.at("cash", end))
    floating, float_notes, float_ev = _floating_amount(out.extraction, debt.value if debt else None,
                                                       user.get("floating_debt"))

    def thresholds(indicator: str) -> list[tuple[Threshold, str]]:
        if user.get(indicator) is not None:
            return [(Threshold(user[indicator], "user", "사용자 입력"), "사용자 입력")]
        out_ = [(reverse.default_threshold(indicator), "기본 규칙")]
        metric = {"interest_coverage": "interest_coverage", "net_debt_to_ebitda": "leverage"}[indicator]
        for v in (out.extraction.of("covenant") if out.extraction else []):
            if v.item.metric == metric:
                out_.append((Threshold(v.values["threshold"], "disclosed", f"{v.item.facility}: {v.item.quote}"),
                             "공시 약정 (정의 차이 주의)"))
                break
        return out_

    for key, basis in (("ebitda", "공시 EBITDA"), ("ebitda_adjusted", "조정 EBITDA")):
        e = out.indicators.get(key)
        if e is None or e.value is None:
            continue
        for th, label in thresholds("interest_coverage"):
            out.scenarios.append(Scenario(reverse.ebitda_drop_to_coverage(e.value, interest, th), basis, label))
            r = reverse.rate_rise_to_coverage(e.value, interest, floating, th)
            r.evidence += float_ev
            out.scenarios.append(Scenario(r, basis, label, list(float_notes)))
        for th, label in thresholds("net_debt_to_ebitda"):
            out.scenarios.append(Scenario(reverse.ebitda_drop_to_leverage(nd, e.value, th), basis, label, list(debt_note)))

    prev = indicators.compute(book, indicators._one_year_before(end))
    recent, ev_unknowns = events.scan(src, data.filings, indicators._one_year_before(as_of), as_of)
    out.unknowns += ev_unknowns
    out.counters = counter.find(book, out.indicators, prev, recent, out.extraction)

    out.ledger = _ledger(out, query, as_of)
    return out


_STATEMENTS = {
    "ebitda_drop_to_coverage": ("이자보상배율이 기준 이상으로 유지된다", "interest_coverage", "above"),
    "rate_rise_to_coverage": ("금리가 올라도 이자보상배율이 기준 이상으로 유지된다", "interest_coverage", "above"),
    "ebitda_drop_to_leverage": ("순차입금/EBITDA가 기준 이하로 유지된다", "net_debt_to_ebitda", "below"),
}


def _ledger(out: ProbeResult, query: str, as_of: str) -> Ledger:
    lg = Ledger(query, out.name)
    n = 0
    for s in out.scenarios:
        r = s.result
        if r.status not in ("computed", "breached") or s.ebitda_basis != "공시 EBITDA":
            continue
        statement, ind, direction = _STATEMENTS[r.template]
        n += 1
        inputs = {"floating_debt": r.inputs["floating_debt"]} if r.template == "rate_rise_to_coverage" else {}
        inputs["margin_at_record"] = r.shock  # % of EBITDA, or bp for the rate path
        if r.current is not None:
            inputs["value_at_record"] = r.current
        lg.add(Assumption(f"A{n}", f"{statement} ({s.threshold_label})", "financial", ind, direction, r.threshold,
                          path_template=r.template, recorded_at=as_of,
                          source_url=out.filing.url if out.filing else "",
                          inputs=inputs, input_notes=list(s.input_notes)))
    for v in (out.extraction.of("customer") if out.extraction else []):
        n += 1
        lg.add(Assumption(f"A{n}", f"주요 고객({v.item.name}) 매출 비중이 유지된다", "demand", "", "above", None,
                          source_quote=v.item.quote, source_url=v.evidence.url, recorded_at=as_of))
    return lg
