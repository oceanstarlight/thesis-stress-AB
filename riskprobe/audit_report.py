"""Audit report (Markdown). Every state, date and type comes from ``audit.run``; no LLM here."""

from __future__ import annotations

from datetime import date

from riskprobe.audit import AuditResult
from riskprobe.report import num

STATE_KO = {"supported": "유지", "weakened": "약화", "mixed": "혼합(공시·조정 EBITDA 엇갈림)", "insufficient": "근거 부족"}
UNIT = {"interest_coverage": "x", "net_debt_to_ebitda": "x"}


def render(res: AuditResult) -> str:
    L = [f"# 투자 판단 감사 보고서: {res.name or res.entity}", "",
         f"- 판단 기준일(T0): {res.t0} · 재생 종료일: {res.end}",
         "- 각 시점의 판정은 **그 공시가 나온 날까지 공개된 정보만으로** 다시 계산했다. 최초 경고 시점은 기계적 신호가 공개된 날이며, "
         "그날 매도했어야 한다는 뜻이 아니고 결과의 원인이라고 단정하지 않는다.", ""]

    L += ["## 1. 가정별 진단", "", "| 가정 | 기준 | T0 상태 | 최초 경고 | 실패 유형 | 가정 무리 신호 |", "|---|---|---|---|---|---|"]
    for aa in res.audits:
        a = aa.assumption
        base = aa.evaluations[0] if aa.evaluations else None
        fw = f"{aa.first_warning.date} ({aa.first_warning.filing.form if aa.first_warning.filing else '기준일 스냅샷'})" if aa.first_warning else "-"
        fragile = {True: "있음", False: "없음", None: "판단 불가"}[aa.fragile]
        th = f"{num(a.threshold.value, 'x')} {'이상' if a.direction == 'above' else '이하'} ({a.threshold.source})" if a.threshold else "-"
        L.append(f"| {a.id} {a.statement} | {th} | {STATE_KO.get(base.status, '-') if base else '-'} | {fw} | **{aa.failure_type}** | {fragile} |")
    L.append("")
    for aa in res.audits:
        L.append(f"- **{aa.assumption.id} {aa.failure_type}**: " + " / ".join(aa.reasons))
    L.append("")

    L += ["## 2. 시간순 재생", ""]
    for aa in res.audits:
        a = aa.assumption
        L += [f"### {a.id} {a.statement}", "", "| 공개일 | 공시 | 재무 기준 기간 말 | 값(공시 EBITDA) | 값(조정 EBITDA) | 상태 |", "|---|---|---|---|---|---|"]
        for e in aa.evaluations:
            src = "기준일 스냅샷" if e.is_baseline else f"[{e.filing.form}]({e.filing.url})"
            mark = " ⚠" if aa.first_warning is e else ""
            val = "EBITDA ≤ 0" if e.value is None and e.status in ("weakened", "mixed") else num(e.value, UNIT.get(a.indicator, 'x'))
            L.append(f"| {e.date} | {src} | {e.period_end} | {val} | "
                     f"{num(e.value_adjusted, UNIT.get(a.indicator, 'x'))} | {STATE_KO[e.status]}{mark} |")
        L.append("")

    L += ["## 3. 같은 기간의 수시공시 (규칙 분류, 원인 단정 아님)", "", "| 공개일 | T0 대비 | 분류 | 중요도 | 원문 |", "|---|---|---|---|---|"]
    for ev in res.events:
        when = "이전(당시 알 수 있었음)" if ev.date <= res.t0 else "이후"
        L.append(f"| {ev.date} | {when} | {', '.join(ev.labels) or '-'} | {ev.severity} | [8-K]({ev.filing.url}) |")
    L.append("")

    L += ["## 4. 당시 알 수 있었던 것과 나중에 알게 된 것", ""]
    for aa in res.audits:
        base = aa.evaluations[0] if aa.evaluations else None
        after = [e for e in aa.evaluations[1:] if e.status in ("weakened", "mixed")]
        L.append(f"- {aa.assumption.id}: 기준일 스냅샷 상태 **{STATE_KO.get(base.status, '-') if base else '-'}**"
                 + (f", 이후 약화가 처음 공개된 날 **{after[0].date}**" if after else ", 이후 약화 공개 없음"))
    first_event = next((e for e in res.events if e.date > res.t0 and e.severity == "high"), None)
    first_fin = min((aa.first_warning.date for aa in res.audits if aa.first_warning and aa.first_warning.filing), default=None)
    if first_event:
        line = f"- 기준일 이후 첫 고위험 수시공시: **{first_event.date}** ({', '.join(first_event.labels)})"
        if first_fin:
            gap = (date.fromisoformat(first_fin) - date.fromisoformat(first_event.date)).days
            line += (f". 재무 지표의 첫 경고({first_fin})보다 **{gap}일 먼저** 공개됨" if gap > 0
                     else f". 재무 지표의 첫 경고({first_fin})와 같은 시기이거나 그 뒤")
        L.append(line)
    alerts_before = [e for e in res.events if e.date <= res.t0 and e.severity in ("high", "medium")]
    alerts_after = [e for e in res.events if e.date > res.t0 and e.severity in ("high", "medium")]
    L.append(f"- 기준일 전 1년 경고성 수시공시: {len(alerts_before)}건, 기준일 이후: {len(alerts_after)}건")
    L.append("")

    L += ["## 5. 데이터 공백·분석 한계", ""]
    seen = set()
    for u in res.unknowns:
        if u.message not in seen:
            seen.add(u.message)
            L.append(f"- {u.message}")
    L.append("- 실패 유형은 코드 규칙으로 정했다(`riskprobe/audit.py`). 경고 신호와 결과의 인과관계는 판단하지 않는다.")
    L.append("")
    return "\n".join(L)
