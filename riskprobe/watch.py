"""Watch (PLANS.md 7.2): while holding, what changed since the last check, and is any recorded
assumption now closer to breaking?

For each ledger on the watchlist and a window (since, until]:
1. New periodic reports: the ledger's assumptions are re-evaluated as of each filing date
   and compared with the state at ``since``. A worse state is an alert.
2. New current reports (8-K): rule-tagged events of high or medium severity are alerts.
3. Rates: SOFR and the 10-year Treasury over the window. If either moved at least
   config.WATCH_RATE_TRIGGER_BP, every rate-path assumption is re-solved on the latest
   point-in-time EBITDA and interest with the floating debt recorded in the ledger, and the
   remaining headroom (shock still absorbable minus the SOFR move since the decision) is shown.
No LLM call is made: with nothing new, a run costs only the HTTP requests.

``scenario`` answers "if this happened now": a rate shock and/or an EBITDA shock applied to
every watched assumption, giving the list of companies that would cross or near a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riskprobe import audit, config, events, indicators, pit, quality, reverse
from riskprobe.ledger import Ledger
from riskprobe.models import Unknown
from riskprobe.sources import rates
from riskprobe.sources import market

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
WORSE = {("supported", "mixed"), ("supported", "weakened"), ("mixed", "weakened"),
         ("insufficient", "weakened"), ("insufficient", "mixed")}


@dataclass
class Alert:
    entity: str
    date: str
    kind: str  # 지표 | 수시공시 | 금리
    severity: str  # high | medium | info
    message: str
    url: str = ""


@dataclass
class EntityState:
    entity: str
    name: str
    states: dict[str, str] = field(default_factory=dict)  # assumption id -> status at until
    rate_headroom: dict[str, float | None] = field(default_factory=dict)  # assumption id -> bp left


@dataclass
class WatchResult:
    since: str
    until: str
    alerts: list[Alert] = field(default_factory=list)
    entities: list[EntityState] = field(default_factory=list)
    rate_moves: dict[str, tuple[float, str, str]] = field(default_factory=dict)  # key -> (bp, from, to)
    unknowns: list[Unknown] = field(default_factory=list)


def _book(facts, excluded, d: str) -> indicators.Book:
    return indicators.Book(pit.snapshot(facts, d, exclude=excluded))


def _rate_headroom(a, book: indicators.Book, sofr_move_since_record: float | None,
                   rate_label: str = "SOFR") -> tuple[float | None, str]:
    """Shock (bp) the latest EBITDA and interest can still absorb with the recorded floating
    debt, minus the floating reference rate's move (SOFR, CD 91-day) since the decision date."""
    end = book.anchor()
    if end is None or "floating_debt" not in a.inputs:
        return None, "변동금리 차입금 기록이 없어 금리 경로를 다시 계산하지 않음"
    e = indicators.compute(book, end).get("ebitda")
    r = reverse.rate_rise_to_coverage(e.value if e else None, book.ttm("interest_expense", end),
                                      a.inputs["floating_debt"], a.threshold)
    if r.shock is None:
        return None, "재계산에 필요한 값이 없음"
    left = r.shock - (sofr_move_since_record or 0.0)
    return left, f"최신 재무({end}) 기준 흡수 가능 {r.shock:,.0f}bp − 기록 이후 {rate_label.split(" (")[0]} 변화 {sofr_move_since_record or 0:+.0f}bp"


def run(ledgers: list[Ledger], since: str, until: str, http) -> WatchResult:
    out = WatchResult(since, until)
    earliest = min([a.recorded_at for lg in ledgers for a in lg.assumptions] + [since])
    series = {}
    currencies = sorted({market.currency(lg.entity) for lg in ledgers}) or ["USD"]
    keys = [k for c in currencies for k in (rates.FLOATING[c], rates.LONG[c])]
    for key in keys:
        s, u = rates.fetch(http, key, indicators._one_year_before(earliest), until)
        out.unknowns += u
        if s is not None:
            series[key] = s
            mv = s.change_bp(since, until)
            if mv is not None:
                out.rate_moves[key] = mv
    rate_trigger = any(abs(mv[0]) >= config.WATCH_RATE_TRIGGER_BP for mv in out.rate_moves.values())
    for key, (bp, a, b) in out.rate_moves.items():
        if abs(bp) >= config.WATCH_RATE_TRIGGER_BP:
            out.alerts.append(Alert("시장", b, "금리", "medium", f"{rates.LABELS[key]} {a} → {b} {bp:+.0f}bp "
                                    f"(트리거 {config.WATCH_RATE_TRIGGER_BP:.0f}bp, 기본 규칙)", series[key].url))

    for lg in ledgers:
        recorded = min((a.recorded_at for a in lg.assumptions), default=until)
        if recorded > until:
            out.unknowns.append(Unknown("watch_not_yet_recorded", "기간 종료일 이후에 기록된 원장은 이번 감시에서 제외함", lg.entity))
            continue
        start = max(since, recorded)  # nothing to watch before the decision was recorded
        src = market.source_for(lg.entity, http)
        data = src.load(lg.entity, since=market.since_for(recorded))
        out.unknowns += [u for u in data.unknowns if u.code not in ("sec_press_release_gap", "sec_coverage_start")]
        if not data.facts:
            continue
        name = data.name or lg.name
        excluded, _ = quality.screen(data.facts, {f.accession: f.report_date for f in data.filings})
        quant = [a for a in lg.assumptions if a.indicator and a.threshold is not None
                 and not a.indicator.startswith("guidance:") and a.path_template != "rate_rise_to_coverage"]
        state = EntityState(lg.entity, name)

        prev = {a.id: audit._evaluate(a, indicators.compute(_book(data.facts, excluded, start)))[2] for a in quant}
        new_reports = [f for f in data.filings if f.form in audit.PERIODIC and start < f.filing_date <= until]
        for f in new_reports:
            ind = indicators.compute(_book(data.facts, excluded, f.filing_date))
            for a in quant:
                st = audit._evaluate(a, ind)[2]
                if (prev[a.id], st) in WORSE:
                    out.alerts.append(Alert(name, f.filing_date, "지표", "high" if st == "weakened" else "medium",
                                            f"{a.id} {a.statement}: {audit_state(prev[a.id])} → {audit_state(st)}", f.url))
                prev[a.id] = st
        state.states = dict(prev)

        evs, ev_u = events.scan(src, data.filings, start, until)
        out.unknowns += ev_u
        for ev in evs:
            if ev.severity in ("high", "medium"):
                out.alerts.append(Alert(name, ev.date, "수시공시", ev.severity, ", ".join(ev.labels), ev.filing.url))

        book = _book(data.facts, excluded, until)
        for a in lg.assumptions:
            if a.path_template != "rate_rise_to_coverage":
                continue
            fkey = market.floating_rate(lg.entity)
            mv = series[fkey].change_bp(a.recorded_at, until) if fkey in series else None
            left, why = _rate_headroom(a, book, mv[0] if mv else None, rates.LABELS[fkey])
            state.rate_headroom[a.id] = left
            if rate_trigger and left is not None:
                grade = reverse.grade(left, "bp")
                sev = {"초과": "high", "근접": "medium"}.get(grade, "info")
                out.alerts.append(Alert(name, until, "금리", sev, f"{a.id} 금리 경로 남은 여유 {left:,.0f}bp → {grade} ({why})"))
        out.entities.append(state)

    out.alerts.sort(key=lambda x: (x.date, SEVERITY_ORDER[x.severity]))
    return out


def audit_state(st: str) -> str:
    return {"supported": "유지", "weakened": "약화", "mixed": "혼합", "insufficient": "근거 부족"}[st]


@dataclass
class ScenarioRow:
    entity: str
    assumption: str
    path: str
    now: float | None
    after: float | None
    threshold: float | None
    verdict: str  # 초과 | 근접 | 유지 | 계산 불가
    note: str = ""


def scenario(ledgers: list[Ledger], as_of: str, http, rate_bp: float = 0.0, ebitda_pct: float = 0.0) -> tuple[list[ScenarioRow], list[Unknown]]:
    """Apply a rate shock (bp, on recorded floating debt) and an EBITDA shock (%, negative = fall)
    to every quantitative assumption, on point-in-time data as of ``as_of``. Conditional
    arithmetic, not a forecast."""
    rows, unknowns = [], []
    for lg in ledgers:
        recorded = min((a.recorded_at for a in lg.assumptions), default=as_of)
        if recorded > as_of:
            continue
        floating = next((a.inputs["floating_debt"] for a in lg.assumptions if "floating_debt" in a.inputs), 0.0)
        data = market.source_for(lg.entity, http).load(lg.entity, since=market.since_for(recorded))
        if not data.facts:
            unknowns += data.unknowns
            continue
        excluded, _ = quality.screen(data.facts, {f.accession: f.report_date for f in data.filings})
        book = _book(data.facts, excluded, as_of)
        end = book.anchor()
        if end is None:
            continue
        ind = indicators.compute(book, end)
        e = ind.get("ebitda").value if ind.get("ebitda") else None
        interest = book.ttm("interest_expense", end)
        debt, cash = book.at("total_debt", end), book.at("cash", end)
        name = data.name or lg.name
        for a in lg.assumptions:
            if (a.threshold is None or a.indicator not in ("interest_coverage", "net_debt_to_ebitda")
                    or a.path_template == "rate_rise_to_coverage"):  # same ratio as the coverage assumption
                continue
            th = a.threshold.value
            e2 = e * (1 + ebitda_pct / 100) if e is not None else None
            if a.indicator == "interest_coverage":
                if e is None or interest is None or interest.value <= 0:
                    rows.append(ScenarioRow(name, a.id, a.statement, None, None, th, "계산 불가", "EBITDA 또는 이자비용 없음"))
                    continue
                fd = floating
                extra = rate_bp / 10_000 * fd
                now, after = e / interest.value, e2 / (interest.value + extra)
                note = (f"변동금리 차입금 {fd / 1e9:,.2f}B 기준 이자 +{extra / 1e6:,.0f}M" if fd else
                        ("변동금리 차입금 기록 없음: 금리 충격 미반영" if rate_bp else ""))
            else:
                if e is None or debt is None or cash is None:
                    rows.append(ScenarioRow(name, a.id, a.statement, None, None, th, "계산 불가", "EBITDA 또는 차입금 없음"))
                    continue
                nd = debt.value - cash.value
                now = nd / e if e > 0 else None
                after = nd / e2 if e2 and e2 > 0 else None
                note = "" if after is not None else "충격 후 EBITDA ≤ 0"
            holds = a.holds(after) if after is not None else False
            if not holds:
                verdict = "초과"
            else:
                margin = abs(after - th) / th * 100
                verdict = "근접" if margin < config.HEADROOM_NEAR["%"] else "유지"
            rows.append(ScenarioRow(name, a.id, a.statement, now, after, th, verdict, note))
    order = {"초과": 0, "근접": 1, "유지": 2, "계산 불가": 3}
    rows.sort(key=lambda r: order[r.verdict])
    return rows, unknowns
