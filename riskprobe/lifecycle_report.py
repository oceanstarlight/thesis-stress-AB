"""Decision card (Markdown) for a lifecycle review. Every state and verdict comes from code."""

from __future__ import annotations

from riskprobe.lifecycle import VERDICT_RULES, LifecycleResult
from riskprobe.report import WARN_CODES, conclusion
from riskprobe.sources import rates

BADGE = {"재검토 필요": "🔴", "주의": "🟡", "유지": "🟢", "판단 불가": "⚪"}


def render(res: LifecycleResult) -> str:
    mode = "투자 전 검토" if res.t0 == res.end else "보유 점검 + 사후 감사"
    L = [f"# 판단 카드: {res.name or res.query}", "",
         f"- 판단 기준일 **{res.t0}** → 점검일 **{res.end}** ({mode})",
         "- 각 시점은 그날까지 공개된 공시만으로 계산했다. 판정은 코드 규칙이며 확률·매매 의견이 아니다.", ""]
    warned = {u.code: u.message for u in res.unknowns if u.code in WARN_CODES}
    L += [f"> ⚠️ {m}" for m in warned.values()] + ([""] if warned else [])
    L += [f"## {BADGE.get(res.verdict, '')} 종합 판정: {res.verdict} (판정 점수 {res.score:.2f}, 확률 아님)", ""]
    L += [f"- {r}" for r in res.reasons]
    L += ["", f"<sub>판정 규칙: {VERDICT_RULES}</sub>", ""]

    L += ["## 가정별 한 줄", "", "| 가정 | 기준 | 기준일 상태·여유 | 최초 경고 | 점검일 상태 | 유형 | 점수 |", "|---|---|---|---|---|---|---|"]
    for r in res.rows:
        L.append(f"| {r.id} {r.statement} | {r.threshold} | {r.at_t0} | {r.first_warning} | {r.now} | {r.failure_type} | {r.score:.2f} |")
    L.append("")

    facts = []
    if res.first_event:
        facts.append(f"기준일 이후 첫 고위험 수시공시: {res.first_event}")
    for key, (bp, a, b) in res.rate_moves.items():
        facts.append(f"{rates.LABELS[key]} {a} → {b}: {bp:+.0f}bp")
    if facts:
        L += ["## 기간 중 사건", ""] + [f"- {f}" for f in facts] + [""]

    if res.scenario:
        L += [f"## 지금 이런 일이 생기면: {res.scenario_label} (조건부 계산)", "",
              "| 가정 | 현재 | 충격 후 | 기준 | 판정 |", "|---|---|---|---|---|"]
        f = lambda v: f"{v:,.2f}배" if v is not None else "-"  # noqa: E731
        for s in res.scenario:
            L.append(f"| {s.assumption} {s.path} | {f(s.now)} | {f(s.after)} | {f(s.threshold)} | **{s.verdict}** |")
        L.append("")

    if res.probe and res.probe.scenarios:
        L += ["## 기준일에 본 깨지는 조건 (Probe)", ""] + [f"- {b}" for b in conclusion(res.probe)[:4]] + [""]
    if res.probe and res.probe.counters:
        L += ["## 기준일에 이미 있던 반증 신호", ""]
        L += [f"- {c.label_ko}: {c.detail[:140]}" for c in res.probe.counters[:5]] + [""]
    return "\n".join(L)
