"""Reverse stress engine: how large a shock breaks a threshold (PLANS.md 5.3).

Each risk path is a code template, not something an LLM draws. A template takes measured
inputs and a threshold and solves for the shock at which the threshold is crossed. Results are
conditional calculations, not forecasts and not probabilities. A missing input is never filled
in; the result says which input is missing.

Templates
- ebitda_drop_to_coverage: EBITDA x (1 - s) / interest = floor        -> s
- rate_rise_to_coverage:   EBITDA / (interest + dr x floating debt) = floor -> dr (bp)
- ebitda_drop_to_leverage: net debt / (EBITDA x (1 - s)) = cap         -> s
- required_growth (Audit): current x (1 + g)^n = target                -> g per period
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from riskprobe import config
from riskprobe.indicators import Measured
from riskprobe.ledger import Threshold
from riskprobe.models import Evidence, Unknown

LABEL = "조건부 계산 (예측 아님)"


@dataclass
class ReverseResult:
    template: str
    label_ko: str
    unit: str  # % | bp
    formula: str
    threshold: Threshold | None
    status: str = "computed"  # computed | breached | not_applicable | missing_input
    shock: float | None = None  # size of the adverse move that reaches the threshold
    current: float | None = None  # the indicator now, for display
    grade: str = ""  # 여유 충분 | 근접 | 초과 | ""
    inputs: dict[str, float] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    note: str = LABEL


def solve_monotone(f: Callable[[float], float], target: float, lo: float, hi: float, tol: float = 1e-9) -> float | None:
    """x in [lo, hi] with f(x) = target for monotone f; None when target is outside f's range."""
    flo, fhi = f(lo) - target, f(hi) - target
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if abs(fm) < tol or hi - lo < tol:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def grade(shock: float | None, unit: str) -> str:
    """Default-rule bands (config.HEADROOM_NEAR); shown with the rule in the UI."""
    if shock is None:
        return ""
    if shock <= 0:
        return "초과"
    return "근접" if shock < config.HEADROOM_NEAR[unit] else "여유 충분"


def _start(template: str, label: str, unit: str, formula: str, threshold: Threshold | None,
           **inputs: Measured | float | None) -> ReverseResult:
    r = ReverseResult(template, label, unit, formula, threshold)
    for k, v in inputs.items():
        if v is None:
            r.unknowns.append(Unknown("reverse_input_missing", f"{label}: 필요한 입력값이 없어 계산하지 않음", k))
            continue
        if isinstance(v, Measured):
            r.inputs[k] = v.value
            r.evidence += [f.evidence() for f in v.facts]
        else:
            r.inputs[k] = float(v)
    if threshold is None:
        r.unknowns.append(Unknown("reverse_threshold_missing", f"{label}: 기준값이 없어 계산하지 않음"))
    if r.unknowns:
        r.status = "missing_input"
    return r


def _finish(r: ReverseResult, shock: float) -> ReverseResult:
    r.shock = shock
    r.status = "breached" if shock <= 0 else "computed"
    r.grade = grade(shock, r.unit)
    return r


def ebitda_drop_to_coverage(ebitda: Measured | float | None, interest: Measured | float | None,
                            floor: Threshold | None) -> ReverseResult:
    r = _start("ebitda_drop_to_coverage", "EBITDA 감소 → 이자보상배율 기준 미달", "%",
               "s = 1 - 기준 배율 × 이자비용 / EBITDA", floor, ebitda=ebitda, interest=interest)
    if r.status == "missing_input":
        return r
    e, i = r.inputs["ebitda"], r.inputs["interest"]
    if i <= 0:
        r.status = "not_applicable"
        r.unknowns.append(Unknown("reverse_not_applicable", "이자비용이 없어 이자보상배율 경로가 해당하지 않음"))
        return r
    r.current = e / i
    if e <= 0:
        r.unknowns.append(Unknown("reverse_negative_ebitda", "EBITDA가 영 이하라 이미 기준을 넘은 상태로 봄"))
        return _finish(r, 0.0)
    return _finish(r, (1 - floor.value * i / e) * 100)


def rate_rise_to_coverage(ebitda: Measured | float | None, interest: Measured | float | None,
                          floating_debt: Measured | float | None, floor: Threshold | None) -> ReverseResult:
    r = _start("rate_rise_to_coverage", "금리 상승 → 변동금리 이자비용 증가 → 이자보상배율 기준 미달", "bp",
               "dr = (EBITDA / 기준 배율 - 이자비용) / 변동금리 차입금", floor,
               ebitda=ebitda, interest=interest, floating_debt=floating_debt)
    if r.status == "missing_input":
        return r
    e, i, fd = r.inputs["ebitda"], r.inputs["interest"], r.inputs["floating_debt"]
    if fd <= 0:
        r.status = "not_applicable"
        r.unknowns.append(Unknown("reverse_not_applicable", "변동금리 차입금이 없어 금리 경로가 해당하지 않음"))
        return r
    r.current = e / i if i > 0 else None
    return _finish(r, (e / floor.value - i) / fd * 10_000)


def ebitda_drop_to_leverage(net_debt: Measured | float | None, ebitda: Measured | float | None,
                            cap: Threshold | None) -> ReverseResult:
    r = _start("ebitda_drop_to_leverage", "EBITDA 감소 → 순차입금/EBITDA 기준 초과", "%",
               "s = 1 - 순차입금 / (기준 배수 × EBITDA)", cap, net_debt=net_debt, ebitda=ebitda)
    if r.status == "missing_input":
        return r
    nd, e = r.inputs["net_debt"], r.inputs["ebitda"]
    if nd <= 0:
        r.status = "not_applicable"
        r.unknowns.append(Unknown("reverse_not_applicable", "순현금 상태라 차입 배수 경로가 해당하지 않음"))
        return r
    if e <= 0:
        r.unknowns.append(Unknown("reverse_negative_ebitda", "EBITDA가 영 이하라 이미 기준을 넘은 상태로 봄"))
        return _finish(r, 0.0)
    r.current = nd / e
    return _finish(r, (1 - nd / (cap.value * e)) * 100)


def required_growth(current: Measured | float | None, target: float | None, periods: int) -> ReverseResult:
    """Growth per period still needed to reach ``target`` (Audit: "what had to happen")."""
    r = _start("required_growth", "목표 달성에 필요한 기간당 성장률", "%", "g = (목표 / 현재)^(1/남은 기간) - 1",
               Threshold(target, "user") if target is not None else None, current=current)
    if r.status == "missing_input":
        return r
    c = r.inputs["current"]
    if periods <= 0 or c <= 0 or target <= 0:
        r.status = "not_applicable"
        r.unknowns.append(Unknown("reverse_not_applicable", "남은 기간이나 현재 값이 양수가 아니라 성장률을 계산하지 않음"))
        return r
    r.shock = ((target / c) ** (1 / periods) - 1) * 100
    r.status = "computed"
    return r


def net_debt(debt: Measured | None, cash: Measured | None) -> Measured | None:
    if debt is None or cash is None:
        return None
    return Measured(debt.value - cash.value, None, debt.period_end, debt.facts + cash.facts, "instant")


def default_threshold(indicator: str) -> Threshold | None:
    v = config.DEFAULT_THRESHOLDS.get(indicator)
    return Threshold(v, "default_rule", f"기본 규칙: {indicator} ({config.DEFAULT_THRESHOLD_BASIS})") if v is not None else None
