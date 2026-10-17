"""Watch brief (Markdown): alerts in the window, current states, rate moves, scenario table."""

from __future__ import annotations

from riskprobe import config
from riskprobe.sources import rates
from riskprobe.watch import ScenarioRow, WatchResult, audit_state

SEV_KO = {"high": "높음", "medium": "중간", "info": "참고"}


def render(res: WatchResult, scenario_rows: list[ScenarioRow] | None = None, scenario_label: str = "") -> str:
    L = [f"# 감시 브리프: {res.since} → {res.until}", "",
         "- 판정·경보는 모두 코드 규칙이다(LLM 호출 없음). 각 판정은 그 공시일까지 공개된 정보만 쓴다.",
         f"- 금리 트리거: SOFR 또는 국채 10년물이 기간 중 {config.WATCH_RATE_TRIGGER_BP:.0f}bp 이상 움직이면 금리 경로를 다시 계산(기본 규칙).", ""]
    L += ["## 1. 경보", ""]
    if res.alerts:
        L += ["| 날짜 | 대상 | 종류 | 중요도 | 내용 |", "|---|---|---|---|---|"]
        for a in res.alerts:
            msg = f"[{a.message}]({a.url})" if a.url else a.message
            L.append(f"| {a.date} | {a.entity} | {a.kind} | {SEV_KO[a.severity]} | {msg.replace('|', '/')} |")
    else:
        L.append("- 새 경보 없음")
    L.append("")
    L += ["## 2. 금리 변화", ""]
    for key, (bp, a, b) in res.rate_moves.items():
        L.append(f"- {rates.LABELS[key]}: {a} → {b} {bp:+.0f}bp")
    L.append("")
    L += ["## 3. 감시 대상 현재 상태", "", "| 대상 | 가정 | 상태 |", "|---|---|---|"]
    for e in res.entities:
        for aid, st in e.states.items():
            L.append(f"| {e.name} | {aid} | {audit_state(st)} |")
        for aid, left in e.rate_headroom.items():
            L.append(f"| {e.name} | {aid} (금리 경로) | 남은 여유 {f'{left:,.0f}bp' if left is not None else '계산 불가'} |")
    L.append("")
    if scenario_rows is not None:
        L += [f"## 4. 사건 시나리오: {scenario_label} (조건부 계산, 예측 아님)", "",
              "| 대상 | 가정 | 현재 | 충격 후 | 기준 | 판정 | 비고 |", "|---|---|---|---|---|---|---|"]
        for r in scenario_rows:
            f = lambda v: f"{v:,.2f}배" if v is not None else "-"  # noqa: E731
            L.append(f"| {r.entity} | {r.assumption} {r.path} | {f(r.now)} | {f(r.after)} | {f(r.threshold)} | **{r.verdict}** | {r.note} |")
        L.append("")
    L += ["## 5. 한계", ""]
    seen = set()
    for u in res.unknowns:
        if u.message not in seen:
            seen.add(u.message)
            L.append(f"- {u.message}")
    L.append("- 회사 밖 사건(지정학, 업종 뉴스)은 아직 감시하지 않는다. 회사가 8-K로 공시한 사건만 잡는다.")
    return "\n".join(L) + "\n"
