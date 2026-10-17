"""Probe risk report (Markdown). Code writes every number and every judgment.

The conclusion is written by code from the reverse-stress results. The LLM adds only a
reading without figures: how disclosed risks connect to the paths, and follow-up questions.
Its text is audited (no digits or number words, no probability or trade wording) and dropped
when the audit fails. ``audit``/``fill`` also support ``[[fact_key]]`` placeholders, adapted
from kr-fund-ai-agent ``audit_brief``, for wording that cites figures.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from riskprobe import config, llm, reverse
from riskprobe.probe import ProbeResult

_PLACEHOLDER = re.compile(r"\[\[([a-zA-Z0-9_]+)\]\]")
_LIST_MARKER = re.compile(r"^\s*\d+\.\s", re.MULTILINE)
_NUMBER_WORDS = re.compile(
    r"(?:[일이삼사오육칠팔구십백천만]+\s*(?:퍼센트|프로|배|분의))|퍼센트|절반|두\s*배|세\s*배|"
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty|hundred|"
    r"percent|half|double|triple)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(r"확률|가능성이\s*(?:높|낮)|매수|매도|목표\s*주가|추천")

GRADE_ORDER = {"초과": 0, "근접": 1, "여유 충분": 2, "": 3}


def money(v: float | None) -> str:
    if v is None:
        return "-"
    a = abs(v)
    s = f"${a / 1e9:,.2f}B" if a >= 1e9 else f"${a / 1e6:,.0f}M"
    return f"-{s}" if v < 0 else s


def num(v: float | None, unit: str) -> str:
    if v is None:
        return "-"
    if unit == "USD":
        return money(v)
    if unit == "x":
        return f"{v:,.2f}배"
    if unit in ("%", "%p"):
        return f"{v:,.1f}{unit}"
    if unit == "bp":
        return f"{v:,.0f}bp"
    if unit == "days":
        return f"{v:,.0f}일"
    return f"{v:,.2f}"


def audit(raw: str, facts: dict[str, str]) -> list[str]:
    problems = [f"unknown fact key: {k}" for k in _PLACEHOLDER.findall(raw) if k not in facts]
    stripped = _LIST_MARKER.sub("", _PLACEHOLDER.sub("", raw))
    if re.search(r"\d", stripped):
        problems.append("digits outside placeholders")
    if _NUMBER_WORDS.search(stripped):
        problems.append("number words outside placeholders")
    if re.search(r"\]\]\s*(?:%|%p|bp|배|일|퍼센트)", raw):
        problems.append("unit appended to a placeholder")
    if _FORBIDDEN.search(stripped):
        problems.append("probability or trade recommendation wording")
    return problems


def fill(raw: str, facts: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: facts.get(m.group(1), m.group(0)), raw)


def shock_text(r: reverse.ReverseResult) -> str:
    if r.status == "breached":
        return "이미 초과"
    if r.status == "missing_input":
        return "입력 없음"
    if r.status == "not_applicable":
        return "해당 없음"
    if r.beyond_cap:
        return f"{num(config.RATE_SHOCK_CAP_BP, 'bp')} 초과 (금리에 사실상 둔감)"
    return num(r.shock, r.unit)


_SHORT = {"ebitda_drop_to_coverage": "이자보상배율", "rate_rise_to_coverage": "금리 상승 시 이자보상배율",
          "ebitda_drop_to_leverage": "순차입금/EBITDA"}


def conclusion(res: ProbeResult) -> list[str]:
    """Code-written conclusion: every path, its state and the shock that breaks it."""
    lines = []
    for s in res.scenarios:
        r, name = s.result, _SHORT[s.result.template]
        where = f"{s.ebitda_basis}, {s.threshold_label} {num(r.threshold.value, 'x') if r.threshold else '-'}"
        if r.status == "breached":
            lines.append(f"**{name}** ({where}): 현재 {num(r.current, 'x')}로 기준일에 이미 기준을 넘음 → 초과")
        elif r.status == "computed" and r.beyond_cap:
            lines.append(f"**{name}** ({where}): 금리가 {num(config.RATE_SHOCK_CAP_BP, 'bp')} 넘게 올라도 기준에 닿지 않음 "
                         f"(금리에 사실상 둔감) → {r.grade}")
        elif r.status == "computed" and r.template == "rate_rise_to_coverage":
            lines.append(f"**{name}** ({where}): 금리가 {shock_text(r)} 오르면 기준 도달 → {r.grade}")
        elif r.status == "computed":
            lines.append(f"**{name}** ({where}): 현재 {num(r.current, 'x')}, EBITDA가 {num(r.shock, r.unit)} 줄면 기준 도달 → {r.grade}")
        else:
            lines.append(f"**{name}** ({where}): {shock_text(r)} — 계산하지 않음 (데이터 한계 참고)")
    lines.sort(key=lambda x: (GRADE_ORDER.get(x.rsplit("→ ", 1)[-1], 3) if "→" in x else 4, "조정" in x))
    return lines or ["계산 가능한 위험 경로가 없음 (데이터 한계 참고)"]


class Reading(BaseModel):
    links_ko: list[str] = Field(description="Two or three Korean sentences linking disclosed risks to the risk paths")
    checks_ko: list[str] = Field(description="Two or three Korean follow-up questions an analyst should verify")


READING_SYSTEM = (
    "You assist a credit risk review of one company for an institutional investor. You get the risk "
    "paths that code evaluated (path name, EBITDA basis, threshold label, state) and the risks the "
    "company disclosed. Write in Korean, plain declarative style (~다): links_ko, two or three "
    "sentences on which disclosed risks could move which path and how; checks_ko, two or three "
    "follow-up questions to verify in the filings or with management. Do not restate the states of "
    "the paths as your own judgment, do not write any digits or number words, no probabilities or "
    "likelihoods, no buy or sell views, no English words except the acronym EBITDA."
)


def llm_reading(res: ProbeResult) -> tuple[Reading | None, str]:
    paths = [{"path": s.result.label_ko, "ebitda": s.ebitda_basis, "threshold": s.threshold_label,
              "state": s.result.grade or s.result.status} for s in res.scenarios]
    risks = [{"category": v.item.category, "risk": v.item.summary_ko, "quote": v.item.quote}
             for v in (res.extraction.of("risk") if res.extraction else [])]
    if not risks:
        return None, "공시 위험 요인이 없어 해석을 생략함"
    out, err = llm.structured_call(Reading, READING_SYSTEM, json.dumps({"PATHS": paths, "RISKS": risks}, ensure_ascii=False))
    if out is None:
        return None, err or "no result"
    problems = audit("\n".join(out.links_ko + out.checks_ko), {})
    if problems:
        return None, "; ".join(problems)
    return out, ""


# Input-level limits shown on top: the indicators may not describe this company.
WARN_CODES = ("sec_foreign_filer", "sec_no_periodic", "sec_financial_sector")


def render(res: ProbeResult, use_llm: bool = True) -> str:
    L = [f"# 위험 탐색 보고서: {res.name or res.query}", "",
         f"- 기준일: {res.as_of} (이날까지 공개된 공시만 사용) · 재무 기준 기간 말: {res.anchor or '-'}",
         f"- 연차보고서: {res.filing.form} {res.filing.filing_date} ([원문]({res.filing.url}))" if res.filing else "- 연차보고서: 없음",
         "- 모든 수치는 공시 원문 값으로 코드가 계산했고, 역산 결과는 **조건부 계산(예측 아님)**이다. 확률은 제시하지 않는다.", ""]
    warned = {u.code: u.message for u in res.unknowns if u.code in WARN_CODES}
    L += [f"> ⚠️ {m}" for m in warned.values()] + ([""] if warned else [])

    L += ["## 1. 한눈에 보는 결론 (코드 판정)", ""]
    L += [f"- {b}" for b in conclusion(res)]
    L.append("")
    reading, why = llm_reading(res) if use_llm else (None, "disabled")
    if reading:
        L += ["### 공시 위험 요인과의 연결 (LLM 해석, 숫자 없음)", ""] + [f"- {b}" for b in reading.links_ko]
        L += ["", "### 추가로 확인할 질문", ""] + [f"- {b}" for b in reading.checks_ko] + [""]

    L += ["## 2. 깨지는 조건 (역산)", "", "| 경로 | EBITDA | 기준값 | 현재 | 기준 도달 충격 | 등급 | 입력 출처 |", "|---|---|---|---|---|---|---|"]
    for s in res.scenarios:
        r = s.result
        th = f"{num(r.threshold.value, 'x')} ({s.threshold_label})" if r.threshold else "-"
        shock = shock_text(r)
        L.append(f"| {r.label_ko} | {s.ebitda_basis} | {th} | {num(r.current, 'x')} | {shock} | {r.grade or '-'} | "
                 f"{'; '.join(s.input_notes) or '공시 재무값'} |")
    L += ["", "계산식: " + " / ".join(sorted({f'{s.result.label_ko}: {s.result.formula}' for s in res.scenarios})), ""]
    covs = [s for s in res.scenarios if s.result.threshold and s.result.threshold.source == "disclosed"]
    if covs:
        L.append("공시 약정 기준값 원문 (약정의 지표 정의는 위 계산과 다를 수 있음):")
        for q in sorted({s.result.threshold.note for s in covs}):
            L.append(f"> {q}")
        L.append("")

    L += ["## 3. 결론과 충돌하는 근거 (반증 탐색, 코드 규칙)", ""]
    if res.counters:
        L += ["| 출처 | 신호 | 내용 | 원문 |", "|---|---|---|---|"]
        kinds = {"indicator": "재무 지표", "trend": "1년 추세", "event": "수시공시", "filing": "연차보고서"}
        for c in res.counters:
            links = " ".join(f"[{i}]({u})" for i, u in enumerate(c.urls, 1)) or "-"
            L.append(f"| {kinds[c.source]} | {c.label_ko} | {c.detail.replace('|', '/')} | {links} |")
        L += ["", "반증 신호는 더 들여다볼 이유이며, 위험하다는 판정이 아니다.", ""]
    else:
        L += ["- 기본 규칙에 걸리는 반증 신호 없음 (규칙에 없는 위험이 없다는 뜻은 아님)", ""]

    L += ["## 4. 핵심 지표", "", "| 지표 | 값 | 계산식 |", "|---|---|---|"]
    for ind in res.indicators.values():
        L.append(f"| {ind.label_ko} | {num(ind.value, ind.unit)} | {ind.formula} |")
    L.append("")

    L += ["## 5. 공시에서 확인한 위험 요인", ""]
    ex = res.extraction
    if ex and ex.items:
        for v in ex.of("risk"):
            L.append(f"- **[{v.item.category}]** {v.item.summary_ko}  \n  > {v.item.quote}")
        for v in ex.of("floating_debt") + ex.of("rate_sensitivity") + ex.of("customer"):
            L.append(f"- **[{v.kind}]** 코드가 읽은 값 {v.values}  \n  > {v.item.quote}")
    else:
        L.append("- 문서 기반 위험 요인 없음 (아래 데이터 한계 참고)")
    L.append("")

    L += ["## 6. 데이터 공백·분석 한계", ""]
    seen = set()
    for u in res.unknowns + [u for s in res.scenarios for u in s.result.unknowns] + \
            [u for i in res.indicators.values() for u in i.unknowns]:
        if u.message not in seen:
            seen.add(u.message)
            L.append(f"- {u.message}")
    if not reading and use_llm:
        L.append(f"- LLM 해석을 쓰지 않음 ({why})")
    L.append("")

    L += ["## 7. 출처", ""]
    urls = {}
    for s in res.scenarios:
        for e in s.result.evidence:
            urls.setdefault(e.url, e.title)
    if res.filing:
        urls.setdefault(res.filing.url, f"{res.filing.form} {res.filing.filing_date}")
    for u, t in urls.items():
        L.append(f"- [{t}]({u})")
    L.append("")
    if res.ledger and res.ledger.assumptions:
        L += ["## 8. 가정 원장에 기록할 항목 (사용자 승인 전)", ""]
        for a in res.ledger.assumptions:
            th = f"{a.threshold.value} ({a.threshold.source})" if a.threshold else "정성"
            L.append(f"- {a.id}: {a.statement} · 기준 {th}")
        L.append("")
    return "\n".join(L)
