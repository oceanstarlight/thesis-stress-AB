"""Audit (PLANS.md 7.3): replay a recorded decision through the filings that came after it.

Starting from the ledger's record date T0, every periodic report published up to the end date
is added in filing order. At each one the snapshot is rebuilt as of that filing date (never
later), the indicators are recomputed and each quantitative assumption gets a state:
supported / weakened / mixed (reported and impairment-adjusted EBITDA disagree) /
insufficient. Current reports (8-K) are tagged by rule and shown on the same timeline.

The failure type of each assumption is decided by code rules, never by the LLM:
- 신호 놓침: already weakened (or weakened on reported EBITDA only) in the T0 snapshot
- 상황 변화: supported at T0, then weakened and not recovered at the next report
- 일시적 흔들림: weakened, then supported again at the next report
- 가정 유지: never weakened through the end date
- 판단 불가: no evaluation had the data
High-severity 8-Ks in the year before T0 are listed with each assumption as a note.
"가정 무리" is a flag on top: the safety margin at T0 was smaller than the worst year-on-year
EBITDA decline in the five years before T0. The first warning is the first report at which
the assumption is weakened (or mixed); it is when a mechanical signal became public, not when
anyone should have sold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from riskprobe import events, indicators, pit, quality, reverse
from riskprobe.ledger import Assumption, Ledger, StatusEntry
from riskprobe.models import Unknown
from riskprobe.sources.sec import Filing, SecSource

PERIODIC = ("10-Q", "10-K")
HISTORY_YEARS = 5
TEMPLATE_FOR = {"interest_coverage": reverse.ebitda_drop_to_coverage, "net_debt_to_ebitda": reverse.ebitda_drop_to_leverage}


@dataclass
class Evaluation:
    date: str  # filing date: when this state became knowable
    filing: Filing | None  # None for the T0 baseline
    period_end: str
    value: float | None
    value_adjusted: float | None
    status: str
    is_baseline: bool = False


@dataclass
class AssumptionAudit:
    assumption: Assumption
    evaluations: list[Evaluation] = field(default_factory=list)
    first_warning: Evaluation | None = None
    failure_type: str = ""
    reasons: list[str] = field(default_factory=list)
    fragile: bool | None = None  # 가정 무리 flag; None when it could not be judged


@dataclass
class AuditResult:
    entity: str
    name: str
    t0: str
    end: str
    audits: list[AssumptionAudit] = field(default_factory=list)
    events: list[events.Event] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)


def _state(a: Assumption, v: float | None, v_adj: float | None) -> str:
    if v is None:
        return "insufficient"
    h = a.holds(v)
    if v_adj is not None and a.holds(v_adj) != h:
        return "mixed"
    return "supported" if h else "weakened"


def _broken(ind: indicators.Indicator | None) -> bool:
    """A ratio not computed because EBITDA is zero or negative: the assumption cannot hold."""
    return ind is not None and any(u.code == "indicator_negative_ebitda" for u in ind.unknowns)


def _evaluate(a: Assumption, ind: dict[str, indicators.Indicator]) -> tuple[float | None, float | None, str]:
    base = ind.get(a.indicator)
    adj = ind.get(a.indicator + "_adjusted")
    v = base.value if base else None
    v_adj = adj.value if adj else None
    if _broken(base):
        return v, v_adj, "weakened" if v_adj is None or not a.holds(v_adj) or _broken(adj) else "mixed"
    return v, v_adj, _state(a, v, v_adj)


def _worst_ebitda_decline(book: indicators.Book, t0_anchor: str) -> tuple[float | None, str]:
    """Worst year-on-year TTM EBITDA change (in %) at quarter ends in the years before T0."""
    ends = sorted({e for e in (*book.quarters("revenue"), *book.years("revenue")) if e <= t0_anchor})
    lo = date.fromisoformat(t0_anchor).replace(year=date.fromisoformat(t0_anchor).year - HISTORY_YEARS).isoformat()
    worst, at = None, ""
    for e in ends:
        if e < lo:
            continue
        now = indicators.compute(book, e).get("ebitda")
        prev = indicators.compute(book, indicators._one_year_before(e)).get("ebitda")
        if not now or not prev or now.value is None or prev.value is None or prev.value <= 0:
            continue
        chg = (now.value / prev.value - 1) * 100
        if worst is None or chg < worst:
            worst, at = chg, e
    return worst, at


def _classify(aa: AssumptionAudit, pre_t0_alerts: list[events.Event]) -> None:
    evs = aa.evaluations
    states = [e.status for e in evs]
    base, later = evs[0], evs[1:]
    bad = ("weakened", "mixed")
    if all(s == "insufficient" for s in states):
        aa.failure_type = "판단 불가"
        aa.reasons.append("기준일과 이후 공시 모두에서 이 지표를 표준 재무 태그로 계산할 수 없음"
                          " (Probe에서 문서·사용자 입력값을 썼다면 재생에는 쓰지 않음)")
    elif base.status == "weakened":
        aa.failure_type = "신호 놓침"
        aa.reasons.append("기준일에 공개돼 있던 공시만으로도 이미 기준을 넘었음")
    elif base.status == "mixed":
        aa.failure_type = "신호 놓침"
        aa.reasons.append("기준일에 공시 EBITDA 기준으로는 이미 기준을 넘었고, 손상차손을 더한 조정 EBITDA 기준으로만 유지됨")
    else:
        for i, e in enumerate(later):
            if e.status in bad:
                nxt = later[i + 1] if i + 1 < len(later) else None
                if nxt is not None and nxt.status == "supported":
                    aa.failure_type = "일시적 흔들림"
                    aa.reasons.append(f"{e.date} 공시에서 약화된 뒤 다음 공시({nxt.date})에서 회복")
                    continue
                aa.failure_type = "상황 변화"
                aa.reasons.append(f"기준일에는 유지됐으나 {e.date} 공시부터 약화되어 다음 공시까지 회복하지 않음"
                                  if nxt else f"기준일에는 유지됐으나 마지막 공시({e.date})에서 약화")
                break
        if not aa.failure_type:
            aa.failure_type = "가정 유지"
            aa.reasons.append("종료일까지 공시된 모든 보고서에서 기준을 지킴")
    if pre_t0_alerts:
        aa.reasons.append("참고: 기준일 전 1년 안에 경고성 수시공시가 있었음 (" +
                          ", ".join(f"{e.date} {'/'.join(e.labels)}" for e in pre_t0_alerts[:3]) + ")")
    aa.first_warning = next((e for e in evs if e.status in bad), None)


def run(ledger: Ledger, end: str, http) -> AuditResult:
    t0 = min(a.recorded_at for a in ledger.assumptions) if ledger.assumptions else end
    out = AuditResult(ledger.entity, ledger.name, t0, end)
    src = SecSource(http)
    data = src.load(ledger.entity)
    out.unknowns += data.unknowns
    if not data.facts:
        return out
    out.name = data.name or ledger.name
    excluded, q_unknowns = quality.screen(data.facts, {f.accession: f.report_date for f in data.filings})
    out.unknowns += q_unknowns

    dates = [(t0, None)] + [(f.filing_date, f) for f in data.filings if f.form in PERIODIC and t0 < f.filing_date <= end]
    quant = [a for a in ledger.assumptions if a.indicator and a.threshold is not None
             and a.path_template != "rate_rise_to_coverage"]
    for a in ledger.assumptions:
        if a.path_template == "rate_rise_to_coverage":
            out.unknowns.append(Unknown("audit_rate_path_skipped",
                                        "금리 경로 가정은 재생에서 이자보상배율 가정과 같아 따로 판정하지 않음 (금리 변화는 Watch에서 판정)", a.id))
        elif a not in quant:
            out.unknowns.append(Unknown("audit_qualitative_skipped", "정량 지표가 없는 가정은 이번 재생에서 판정하지 않음", a.id))
    audits = {a.id: AssumptionAudit(a) for a in quant}
    last_anchor, t0_book = None, None
    for d, filing in dates:
        book = indicators.Book(pit.snapshot(data.facts, d, exclude=excluded))
        anchor = book.anchor()
        if t0_book is None:
            t0_book = book
        if anchor is None or (filing is not None and anchor == last_anchor):
            continue  # no new financial period in this filing
        last_anchor = anchor
        ind = indicators.compute(book)
        for a in quant:
            v, v_adj, st = _evaluate(a, ind)
            audits[a.id].evaluations.append(Evaluation(d, filing, anchor, v, v_adj, st, is_baseline=filing is None))

    out.events, ev_unknowns = events.scan(src, data.filings, _minus_year(t0), end)
    out.unknowns += ev_unknowns
    pre_alerts = [e for e in out.events if e.date <= t0 and e.severity == "high"]

    for aa in audits.values():
        if not aa.evaluations:
            aa.failure_type = "판단 불가"
            aa.reasons.append("기준일까지 공개된 재무 값이 없음")
            continue
        _classify(aa, pre_alerts)
        _fragility(aa, t0_book)
        for e in aa.evaluations:
            aa.assumption.history.append(StatusEntry(e.date, e.status, f"{e.period_end} 기준 지표",
                                                     [e.filing.url] if e.filing else []))
    out.audits = list(audits.values())
    return out


def _fragility(aa: AssumptionAudit, t0_book: indicators.Book) -> None:
    """가정 무리 flag: margin at T0 vs the worst EBITDA decline in the five years before."""
    base = aa.evaluations[0]
    solver = TEMPLATE_FOR.get(aa.assumption.indicator)
    if solver is None or base.value is None:
        return
    end = base.period_end
    ind = indicators.compute(t0_book, end)
    e = ind.get("ebitda")
    if e is None or e.value is None:
        return
    if aa.assumption.indicator == "interest_coverage":
        r = solver(e.value, t0_book.ttm("interest_expense", end), aa.assumption.threshold)
    else:
        r = solver(reverse.net_debt(t0_book.at("total_debt", end), t0_book.at("cash", end)), e.value, aa.assumption.threshold)
    worst, at = _worst_ebitda_decline(t0_book, end)
    if r.shock is None or worst is None:
        return
    aa.fragile = r.status == "computed" and -worst >= r.shock
    if aa.fragile:
        aa.reasons.append(f"가정 무리 신호: 기준일 여유(EBITDA {r.shock:.1f}% 감소까지)보다 큰 감소가 "
                          f"기준일 전 {HISTORY_YEARS}년 안에 있었음({at}, 전년 대비 {worst:.1f}%)")


def _minus_year(d: str) -> str:
    return indicators._one_year_before(d)
