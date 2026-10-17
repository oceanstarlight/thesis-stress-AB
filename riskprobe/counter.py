"""Counter-evidence for Probe: what, as of the decision date, argues against "this is safe".

Confirmation bias is the failure Probe guards against, so this step looks only for evidence
that conflicts with a comfortable conclusion. Every rule is code with a stated default
threshold (config.COUNTER_RULES, labeled "기본 규칙"); the LLM is not involved. Sources:
- indicators at the anchor date and one year earlier, from the same point-in-time snapshot;
- 8-K events in the year before the date (rule-tagged, see ``events``);
- risk items the filing extraction verified in the categories that signal stress.
A counter-signal is a reason to look closer, not a finding that the company is unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riskprobe import config, events, indicators
from riskprobe.extract import ExtractionResult


@dataclass
class Counter:
    source: str  # indicator | trend | event | filing
    label_ko: str
    detail: str
    urls: list[str] = field(default_factory=list)


def _v(ind: dict[str, indicators.Indicator], key: str) -> float | None:
    i = ind.get(key)
    return i.value if i else None


def _urls(ind: indicators.Indicator | None) -> list[str]:
    if ind is None:
        return []
    return sorted({f.url for m in ind.inputs.values() for f in m.facts if f.url})[:3]


def find(book: indicators.Book, now: dict[str, indicators.Indicator], prev: dict[str, indicators.Indicator],
         recent_events: list[events.Event], extraction: ExtractionResult | None) -> list[Counter]:
    R = config.COUNTER_RULES
    out: list[Counter] = []

    def level(key: str, test, label: str, rule: str):
        v = _v(now, key)
        if v is not None and test(v):
            out.append(Counter("indicator", label, f"{now[key].label_ko} {v:,.2f} ({rule}, 기본 규칙)", _urls(now[key])))

    level("ocf_to_net_income", lambda v: 0 <= v < R["ocf_to_net_income_min"], "이익의 현금 전환이 약함",
          f"{R['ocf_to_net_income_min']}배 미만")
    level("short_term_debt_share", lambda v: v > R["short_term_debt_share_max"], "단기차입 비중이 높음(차환 위험)",
          f"{R['short_term_debt_share_max']}% 초과")
    level("current_ratio", lambda v: v < R["current_ratio_min"], "유동부채가 유동자산보다 많음", f"{R['current_ratio_min']}배 미만")
    level("inventory_minus_revenue_growth", lambda v: v > R["inventory_minus_revenue_growth_max"], "재고가 매출보다 빠르게 늘어남",
          f"{R['inventory_minus_revenue_growth_max']}%p 초과")
    level("revenue_yoy", lambda v: v < 0, "분기 매출이 전년보다 줄어듦", "0% 미만")

    def trend(key: str, worse_if_down: bool, label: str):
        a, b = _v(now, key), _v(prev, key)
        if a is None or b is None or b == 0:
            return
        chg = (a / b - 1) * 100
        worse = -chg if worse_if_down else chg
        if worse >= R["trend_worse_pct"]:
            out.append(Counter("trend", label, f"{now[key].label_ko} {b:,.2f} → {a:,.2f} (1년 사이 {chg:+.1f}%, "
                                               f"{R['trend_worse_pct']}% 이상 악화, 기본 규칙)", _urls(now[key])))

    trend("interest_coverage", True, "이자보상배율이 1년 전보다 낮아짐")
    trend("net_debt_to_ebitda", False, "차입 배수가 1년 전보다 높아짐")
    a, b = _v(now, "dso"), _v(prev, "dso")
    if a is not None and b is not None and a - b >= R["dso_increase_days"]:
        out.append(Counter("trend", "매출채권 회수 기간이 길어짐",
                           f"매출채권 회전일수 {b:,.0f}일 → {a:,.0f}일 ({R['dso_increase_days']}일 이상 증가, 기본 규칙)", _urls(now["dso"])))

    for ev in recent_events:
        if ev.severity in ("high", "medium"):
            out.append(Counter("event", f"최근 1년 수시공시: {', '.join(ev.labels)}", f"{ev.date} 8-K ({ev.severity})", [ev.filing.url]))

    for v in (extraction.of("risk") if extraction else []):
        if v.item.category in ("liquidity", "covenant", "credit_rating", "refinancing"):
            out.append(Counter("filing", f"연차보고서 위험 서술: {v.item.category}", v.item.quote[:300], [v.evidence.url]))
    return out
