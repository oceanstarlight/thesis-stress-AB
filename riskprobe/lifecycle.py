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

Verdict (shown with every component; a score, not a probability):
- Score per assumption: depth beyond the threshold (1/2/3 points) x weight of the threshold's
  source (default rules count less than user or covenant thresholds); +1 if it got worse
  since T0, x0.5 if it was already breached at T0 and has not worsened; mixed 1, near 0.5.
- Common signals: 8-Ks in the last 90 days (high 2, medium 1, capped), the what-if breaking an
  assumption that holds now (1).
- Total >= review threshold -> 재검토 필요, >= caution threshold -> 주의, else 유지; any
  breached assumption is at least 주의.
- Hard rules, regardless of score: EBITDA <= 0 at the check date, or an 8-K item 1.03 / 2.04 /
  4.02 in the last year -> 재검토 필요.
Weights live in config.VERDICT_SCORE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from riskprobe import audit, config, events, guidance, indicators, probe, quality, reverse, watch
from riskprobe.models import Unknown
from riskprobe.sources import rates
from riskprobe.sources.sec import SecSource

RECENT_ALERT_DAYS = 90
_W = config.VERDICT_SCORE
VERDICT_RULES = (f"가정 점수(기준 초과 정도 1~3점 × 기준값 출처 가중, 기준일 대비 악화 +{_W['worse_since_t0']:g}, "
                 f"기준일부터 초과·악화 없음 ×{_W['known_at_t0_factor']:g}, 혼합 {_W['mixed']:g}, 근접 {_W['near']:g}) + "
                 f"최근 90일 8-K(고 {_W['event_high']:g}, 중 {_W['event_medium']:g}, 최대 {_W['event_cap']:g}) + "
                 f"시나리오 {_W['scenario']:g}. 합계 {_W['review']:g} 이상 재검토 필요, {_W['caution']:g} 이상 주의(기준 초과 가정이 "
                 f"있으면 최소 주의). 강제 규칙: EBITDA ≤ 0, 최근 1년 8-K 파산·조기상환 사유·재작성 → 재검토 필요. "
                 f"점수는 확률이 아님")


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
    broken: bool = False  # EBITDA <= 0 at the check date
    score: float = 0.0
    score_notes: list[str] = field(default_factory=list)


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
    score: float = 0.0
    score_notes: list[str] = field(default_factory=list)  # common signals
    series: list[dict] = field(default_factory=list)  # chart points
    events: list = field(default_factory=list)  # 8-K events considered (window up to the check date)
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

    if out.audit is None:
        data = src.load(query)
        out.events, ev_u = events.scan(src, data.filings, indicators._one_year_before(end), end)
        out.unknowns += ev_u
    else:
        out.events = out.audit.events

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
            row = Row(a.id, a.statement, th, _margin_text(a), "-", now, "-", st, near=grade == "근접")
            if left is not None and left < 0:
                _score_breach(row, a, -left, "bp", None)
            elif row.near:
                _add(row, _W["near"], "근접")
            out.rows.append(row)
            continue
        if aa is None:  # no replay: T0 is the check date
            st = "weakened" if (a.inputs.get("margin_at_record") or 1) <= 0 else "supported"
            grade = reverse.grade(a.inputs.get("margin_at_record"), "%") if "margin_at_record" in a.inputs else ""
            row = Row(a.id, a.statement, th, _margin_text(a) or "-", "-", STATE_KO[st], "-", st, near=grade == "근접")
            v = a.inputs.get("value_at_record")
            if st == "weakened":
                if v is None:
                    row.broken = True
                    _add(row, 3 * _W["source_weight"].get(a.threshold.source, 1.0), "EBITDA ≤ 0")
                else:
                    _score_breach(row, a, _depth_pct(a, v), "%", None)
            elif row.near:
                _add(row, _W["near"], "근접")
            out.rows.append(row)
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
        row = Row(a.id, a.statement, th, at_t0, fw, STATE_KO[st] + now_v + (" · 근접" if near else "") + tail,
                  aa.failure_type, st, near)
        if st == "weakened":
            if last.value is None:  # ratio not computable because EBITDA <= 0
                row.broken = not a.indicator.startswith("guidance:")
                _add(row, 3 * _W["source_weight"].get(a.threshold.source, 1.0), "EBITDA ≤ 0" if row.broken else "기준 초과")
            else:
                t0_val = base.value if base and base.status != "insufficient" else None
                _score_breach(row, a, _depth_pct(a, last.value), "%",
                              (_depth_pct(a, t0_val) if t0_val is not None else None, base.status if base else ""))
        elif st == "mixed":
            _add(row, _W["mixed"], "혼합(공시·조정 EBITDA 판정 엇갈림)")
        elif near:
            _add(row, _W["near"], "근접")
        out.rows.append(row)

    _verdict(out)
    return out


def _add(row: Row, pts: float, why: str) -> None:
    row.score += pts
    row.score_notes.append(f"{why} {pts:+.2f}")


def _depth_pct(a, v: float) -> float:
    """How far ``v`` is beyond the threshold, in % of the threshold (positive = breached)."""
    th = a.threshold.value
    gap = (th - v) if a.direction == "above" else (v - th)
    return gap / abs(th) * 100 if th else 0.0


def _points(depth: float, unit: str) -> int:
    lo, hi = _W["depth_bp"] if unit == "bp" else _W["depth_pct"]
    return 1 if depth < lo else 2 if depth < hi else 3


def _score_breach(row: Row, a, depth: float, unit: str, t0: tuple[float | None, str] | None) -> None:
    w = _W["source_weight"].get(a.threshold.source, 1.0)
    pts = _points(depth, unit) * w
    why = f"기준 {depth:,.0f}{unit} 초과({_points(depth, unit)}점 × 출처 {a.threshold.source} {w:g})"
    if t0 is not None:
        t0_depth, t0_status = t0
        if t0_status == "weakened" and t0_depth is not None and depth <= t0_depth:
            pts *= _W["known_at_t0_factor"]
            why += f" × 기준일부터 초과·악화 없음 {_W['known_at_t0_factor']:g}"
        else:
            pts += _W["worse_since_t0"]
            why += " + 기준일 대비 악화"
    _add(row, pts, why)


def _verdict(out: LifecycleResult) -> None:
    recent_cut = (date.fromisoformat(out.end) - timedelta(days=RECENT_ALERT_DAYS)).isoformat()
    hard_cut = (date.fromisoformat(out.end) - timedelta(days=config.VERDICT_HARD_8K_DAYS)).isoformat()
    evs = [e for e in out.events if e.date <= out.end]
    ev_pts = 0.0
    for e in evs:
        if e.date > recent_cut and e.severity in ("high", "medium"):
            ev_pts += _W["event_high"] if e.severity == "high" else _W["event_medium"]
            out.score_notes.append(f"최근 90일 8-K {e.date} {', '.join(e.labels)} ({e.severity})")
    ev_pts = min(ev_pts, _W["event_cap"])
    holding_ids = {r.id for r in out.rows if r.status_now == "supported"}
    scen_break = [s for s in out.scenario if s.verdict == "초과" and s.assumption in holding_ids]
    sc_pts = _W["scenario"] if scen_break else 0.0
    if scen_break:
        out.score_notes.append(f"시나리오({out.scenario_label})에서 {', '.join(s.assumption for s in scen_break)} 기준 초과")
    out.score = sum(r.score for r in out.rows) + ev_pts + sc_pts

    hard = [f"{r.id}: 점검일 EBITDA ≤ 0" for r in out.rows if r.broken]
    for e in evs:
        items = {i.strip() for i in (e.filing.items or "").split(",")}
        for item, label in config.VERDICT_HARD_8K_ITEMS.items():
            if item in items and e.date > hard_cut:
                hard.append(f"{e.date} 8-K {item} {label}")
    breached = any(r.status_now == "weakened" for r in out.rows)
    if hard:
        out.verdict = "재검토 필요"
    elif out.score >= _W["review"]:
        out.verdict = "재검토 필요"
    elif out.score >= _W["caution"] or breached:
        out.verdict = "주의"
    else:
        out.verdict = "유지"
    reasons = [f"강제 규칙: {h}" for h in hard]
    reasons.append(f"판정 점수 {out.score:.2f} (재검토 {_W['review']:g} · 주의 {_W['caution']:g} 이상, 확률 아님)")
    reasons += [f"{r.id} {r.score:+.2f}: {'; '.join(r.score_notes)}" for r in out.rows if r.score_notes]
    if ev_pts:
        reasons.append(f"최근 수시공시 {ev_pts:+.2f}")
    reasons += [f"{n}" for n in out.score_notes]
    if breached and not hard and out.score < _W["caution"]:
        reasons.append("기준을 넘은 가정이 있어 최소 '주의'")
    out.reasons = reasons
