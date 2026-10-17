"""Lifecycle review: one input (company, decision date T0, check date), one output (a decision card).

Probe, Watch and Audit share the data layer and the ledger, so they run as one pipeline:
1. Probe as of T0: where the "safe" view breaks; its assumptions become the ledger
   (optionally plus the company's own guidance stated before T0).
2. One replay from T0 to the check date (Audit's loop): every periodic report re-evaluates the
   assumptions, 8-Ks are rule-tagged, and guidance restatements are read. Watch adds only what
   the replay lacks: the rate move since T0 and each rate path's remaining headroom.
3. Synthesis by code rules: an overall verdict, one line per assumption, and a what-if scenario.
With T0 equal to the check date this is a pre-investment review (Probe + scenario); with T0 in
the past it is a holding check and a post-hoc audit at once.

Verdict rules (shown with the result):
- 재검토 필요: an assumption is weakened at the check date
- 주의: an assumption is mixed or near its threshold, a high-severity 8-K in the last 90 days,
  or the scenario breaks an assumption that currently holds
- 유지: none of the above
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from riskprobe import audit, config, guidance, indicators, probe, quality, reverse, watch
from riskprobe.models import Unknown
from riskprobe.sources import rates
from riskprobe.sources.sec import SecSource

RECENT_ALERT_DAYS = 90
VERDICT_RULES = ("재검토 필요: 점검일에 약화된 가정이 있음 / 주의: 혼합·근접 가정, 최근 90일 고위험 수시공시, "
                 "또는 시나리오에서 지금 유지 중인 가정이 깨짐 / 유지: 그 외")


@dataclass
class Row:
    id: str
    statement: str
    threshold: str
    at_t0: str  # state at T0 with the margin
    first_warning: str
    now: str  # state at the check date
    failure_type: str
    status_now: str  # supported | weakened | mixed | insufficient
    near: bool = False


@dataclass
class LifecycleResult:
    query: str
    t0: str
    end: str
    name: str = ""
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    probe: probe.ProbeResult | None = None
    audit: audit.AuditResult | None = None
    scenario: list[watch.ScenarioRow] = field(default_factory=list)
    scenario_label: str = ""
    rate_moves: dict[str, tuple[float, str, str]] = field(default_factory=dict)
    first_event: str = ""  # first high-severity 8-K after T0
    series: list[dict] = field(default_factory=list)  # chart points
    unknowns: list[Unknown] = field(default_factory=list)


STATE_KO = {"supported": "유지", "weakened": "약화", "mixed": "혼합", "insufficient": "근거 부족"}


def _margin_text(a) -> str:
    m = a.inputs.get("margin_at_record")
    if m is None:
        return ""
    unit = "bp" if a.path_template == "rate_rise_to_coverage" else "%"
    if m <= 0:
        return "이미 기준 초과"
    if unit == "bp" and m > config.RATE_SHOCK_CAP_BP:
        return f"금리 {config.RATE_SHOCK_CAP_BP:,.0f}bp 넘게 올라도 유지 (사실상 둔감)"
    lever = "금리" if unit == "bp" else "EBITDA"
    return f"{lever} {m:,.0f}{unit} {'상승' if unit == 'bp' else '감소'}까지 여유 ({reverse.grade(m, unit)})"


def run(query: str, t0: str, end: str, http, user: dict | None = None, include_guidance: bool = False,
        rate_bp: float = 100.0, ebitda_pct: float = -20.0) -> LifecycleResult:
    out = LifecycleResult(query, t0, end)
    out.probe = probe.run(query, t0, http, user)
    out.name = out.probe.name
    out.unknowns += out.probe.unknowns
    lg = out.probe.ledger
    if lg is None:
        out.verdict, out.reasons = "판단 불가", ["기준일까지 공개된 재무 값이 없음"]
        return out

    src = SecSource(http)
    if include_guidance:
        data = src.load(query)
        targets, g_unknowns = guidance.latest_before(src, data.filings, t0)
        out.unknowns += g_unknowns
        for a in guidance.to_assumptions(targets, t0, start_id=1):
            lg.add(a)

    quant = [a for a in lg.assumptions if a.indicator and a.threshold is not None]
    states_now: dict[str, str] = {}
    if end > t0:
        out.audit = audit.run(lg, end, http)
        out.unknowns += out.audit.unknowns
        first_high = next((e for e in out.audit.events if e.date > t0 and e.severity == "high"), None)
        out.first_event = f"{first_high.date} ({', '.join(first_high.labels)})" if first_high else ""
        for aa in out.audit.audits:
            ev = aa.evaluations
            states_now[aa.assumption.id] = ev[-1].status if ev else "insufficient"
            for e in ev:
                if e.value is not None:
                    out.series.append({"가정": aa.assumption.id, "공개일": e.date, "값": e.value,
                                       "기준": aa.assumption.threshold.value})

    # Rates since T0 and each rate path's remaining headroom at the check date.
    rate_left: dict[str, tuple[float | None, str]] = {}
    rate_paths = [a for a in lg.assumptions if a.path_template == "rate_rise_to_coverage"]
    if rate_paths and end > t0:
        sofr, r_unknowns = rates.fetch(http, "sofr", indicators._one_year_before(t0), end)
        out.unknowns += r_unknowns
        if sofr is not None:
            mv = sofr.change_bp(t0, end)
            if mv:
                out.rate_moves["sofr"] = mv
        data = src.load(query)
        excluded, _ = quality.screen(data.facts, {f.accession: f.report_date for f in data.filings})
        book = watch._book(data.facts, excluded, end)
        for a in rate_paths:
            rate_left[a.id] = watch._rate_headroom(a, book, out.rate_moves["sofr"][0] if "sofr" in out.rate_moves else None)

    if rate_bp or ebitda_pct:
        out.scenario, s_unknowns = watch.scenario([lg], end, http, rate_bp, ebitda_pct)
        out.unknowns += s_unknowns
        out.scenario_label = f"금리 {rate_bp:+.0f}bp, EBITDA {ebitda_pct:+.0f}%"

    audits = {aa.assumption.id: aa for aa in (out.audit.audits if out.audit else [])}
    for a in quant:
        unit = "%" if a.indicator.startswith("guidance:") else "배"
        th = f"{a.threshold.value:,.2f}{unit} {'이상' if a.direction == 'above' else '이하'} ({a.threshold.source})"
        aa = audits.get(a.id)
        if a.path_template == "rate_rise_to_coverage":
            left, why = rate_left.get(a.id, (a.inputs.get("margin_at_record"), "기록 시점 값"))
            grade = reverse.grade(left, "bp") if left is not None else ""
            st = "weakened" if grade == "초과" else "supported" if left is not None else "insufficient"
            now = ("계산 불가" if left is None else
                   f"남은 여유 {config.RATE_SHOCK_CAP_BP:,.0f}bp 초과 (사실상 둔감)" if left > config.RATE_SHOCK_CAP_BP else
                   f"남은 여유 {left:,.0f}bp ({grade})")
            out.rows.append(Row(a.id, a.statement, th, _margin_text(a), "-", now, "-", st, near=grade == "근접"))
            continue
        if aa is None:  # no replay: T0 is the check date
            st = "weakened" if (a.inputs.get("margin_at_record") or 1) <= 0 else "supported"
            grade = reverse.grade(a.inputs.get("margin_at_record"), "%") if "margin_at_record" in a.inputs else ""
            out.rows.append(Row(a.id, a.statement, th, _margin_text(a) or "-", "-", STATE_KO[st], "-", st,
                                near=grade == "근접"))
            continue
        base = aa.evaluations[0] if aa.evaluations else None
        stated = [e for e in aa.evaluations if e.status != "insufficient"]
        last = stated[-1] if stated else (aa.evaluations[-1] if aa.evaluations else None)
        dropped = bool(stated) and aa.evaluations[-1].status == "insufficient"
        if base and base.status == "insufficient" and _margin_text(a):
            at_t0 = f"{_margin_text(a)} (Probe는 문서·입력값 사용, 재생은 표준 태그만이라 불가)"
        else:
            at_t0 = STATE_KO[base.status] if base else "-"
            if _margin_text(a):
                at_t0 += f" · {_margin_text(a)}"
        fw = f"{aa.first_warning.date}" + (f" ({aa.first_warning.filing.form})" if aa.first_warning and aa.first_warning.filing else
                                           " (기준일)") if aa.first_warning else "-"
        now_v = (f" ({last.value:,.2f}{unit})" if last and last.value is not None
                 else " (EBITDA ≤ 0)" if last and last.status == "weakened" and not a.indicator.startswith("guidance:")
                 else "")
        st = last.status if last else states_now.get(a.id, "insufficient")
        near = False
        if last and last.value is not None and st == "supported":
            near = abs(last.value - a.threshold.value) / abs(a.threshold.value) * 100 < config.HEADROOM_NEAR["%"]
        tail = (f" · 이후 실적 발표에서 언급 없음({aa.evaluations[-1].date})" if dropped and a.indicator.startswith("guidance:")
                else f" · 마지막 공시({aa.evaluations[-1].date})는 계산 불가" if dropped else "")
        out.rows.append(Row(a.id, a.statement, th, at_t0, fw, STATE_KO[st] + now_v + (" · 근접" if near else "") + tail,
                            aa.failure_type, st, near))

    _verdict(out)
    return out


def _verdict(out: LifecycleResult) -> None:
    reasons = []
    weak = [r for r in out.rows if r.status_now == "weakened"]
    if weak:
        out.verdict = "재검토 필요"
        reasons += [f"{r.id} 약화: {r.statement}" for r in weak]
    caution = [r for r in out.rows if r.status_now == "mixed" or r.near]
    recent_cut = (date.fromisoformat(out.end) - timedelta(days=RECENT_ALERT_DAYS)).isoformat()
    recent = [e for e in (out.audit.events if out.audit else []) if recent_cut < e.date <= out.end and e.severity == "high"]
    holding_ids = {r.id for r in out.rows if r.status_now == "supported"}
    scen_break = [s for s in out.scenario if s.verdict == "초과" and s.assumption in holding_ids]
    if not weak:
        if caution or recent or scen_break:
            out.verdict = "주의"
        else:
            out.verdict = "유지"
    reasons += [f"{r.id} {'혼합' if r.status_now == 'mixed' else '근접'}: {r.statement}" for r in caution]
    reasons += [f"최근 {RECENT_ALERT_DAYS}일 고위험 수시공시 {e.date}: {', '.join(e.labels)}" for e in recent[:3]]
    reasons += [f"시나리오({out.scenario_label})에서 {s.assumption} 기준 초과" for s in scen_break]
    out.reasons = reasons or ["약화·근접 가정, 최근 고위험 경보, 시나리오 초과 모두 없음"]
