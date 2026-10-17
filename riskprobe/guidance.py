"""Company guidance (or an analyst memo) as the thesis, and how it was restated later.

A thesis written today about a past date knows the outcome. The company's own forward-looking
statements, dated by their filing, do not: they are what management said the business would
do, as of that day. This module:
1. picks forward-looking sentences from the annual report and the earnings / Regulation FD
   releases (8-K items 2.02 and 7.01, Exhibit 99) around a date, by keyword rules;
2. has the LLM list quantitative targets with verbatim quotes, which code verifies and parses;
3. turns targets into ledger assumptions (threshold = the low end, source = the quote);
4. re-reads later releases so Audit can see when the same target was restated lower.

The same extraction runs on a user memo (source "user"), verified against the memo text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from riskprobe import events, llm, text
from riskprobe.extract import parse_pct
from riskprobe.ledger import Assumption, Threshold
from riskprobe.models import Evidence, Unknown
from riskprobe.sources.sec import Filing
from riskprobe.text import squash

Metric = Literal["revenue", "eps", "dividend_per_share", "ebitda", "cash_flow", "other"]

GUIDANCE_KEYWORDS = re.compile(
    r"expect|guidance|outlook|target|reasonable range|through (?:at least )?20\d\d|per year|long[- ]term|"
    r"reaffirm|forecast|we (?:continue to )?(?:see|believe)", re.I)
_HAS_PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
_YEAR = re.compile(r"\b(20\d\d)\b")


class Target(BaseModel):
    metric: Metric
    metric_text: str = Field(description="The measure exactly as written, e.g. 'limited partner distributions per unit'")
    low_text: str = Field(description="Lowest number of the stated annual growth range exactly as written, e.g. '12%' "
                                      "(not a point target inside the range)")
    high_text: str = Field(description="High end exactly as written, or empty when a single value is stated")
    horizon_text: str = Field(description="Time frame exactly as written, e.g. 'through at least 2026', or empty")
    quote: str = Field(description="Verbatim sentence containing metric_text, low_text, high_text and horizon_text")


class Targets(BaseModel):
    targets: list[Target]


SYSTEM = (
    "You read forward-looking statements of a company (or an analyst's investment memo). List only "
    "explicit quantitative annual growth expectations for a named measure (revenue, earnings per "
    "share, dividends or distributions per share/unit, EBITDA, cash flow), stated by the author as "
    "their own expectation. Skip historical results, peers and macro forecasts. Copy the measure, "
    "the low and high rates, the time frame and the sentence verbatim; never compute or infer a "
    "figure. Return an empty list when there is none."
)


@dataclass
class VerifiedTarget:
    target: Target
    low: float
    high: float | None
    horizon_year: int | None
    evidence: Evidence


@dataclass
class TargetResult:
    targets: list[VerifiedTarget] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)


def forward_paragraphs(paras: list[str]) -> list[str]:
    return [p for p in paras if GUIDANCE_KEYWORDS.search(p) and _HAS_PCT.search(p)]


def verify(t: Target, doc: str) -> tuple[tuple[float, float | None, int | None] | None, list[str]]:
    problems = []
    if not t.quote or squash(t.quote) not in squash(doc):
        problems.append("quote not found")
    for s in (t.metric_text, t.low_text, t.high_text, t.horizon_text):
        if s and squash(s) not in squash(t.quote):
            problems.append(f"'{s}' not inside quote")
    low, high = parse_pct(t.low_text), parse_pct(t.high_text) if t.high_text else None
    if low is None:
        problems.append("low end is not a percentage")
    if t.high_text and high is None:
        problems.append("high end is not a percentage")
    m = _YEAR.search(t.horizon_text or "")
    return ((low, high, int(m.group(1)) if m else None) if not problems else None), problems


def extract_targets(paras: list[str], title: str, url: str, published_at: str, source: str = "sec") -> TargetResult:
    res = TargetResult()
    picked = forward_paragraphs(paras)
    if not picked:
        return res
    doc = "\n".join(picked)
    out, err = llm.structured_call(Targets, SYSTEM, f"SOURCE: {title}\n\nTEXT:\n{doc}")
    if out is None:
        res.unknowns.append(Unknown("guidance_unavailable", "전망 문장 추출을 실행하지 못함", err or ""))
        return res
    rejected = []
    for t in out.targets:
        parsed, problems = verify(t, doc)
        if problems:
            rejected.append(f"{problems} :: {t.quote[:80]}")
            continue
        low, high, year = parsed
        res.targets.append(VerifiedTarget(t, low, high, year, Evidence(source, title, url, published_at=published_at,
                                                                       locator=t.metric, quote=t.quote)))
    if rejected:
        res.unknowns.append(Unknown("guidance_rejected", "원문에서 확인되지 않는 전망 추출 결과를 버림", " | ".join(rejected)[:1500]))
    return res


def releases(src, filings: list[Filing], start: str, end: str) -> list[Filing]:
    """Earnings and Regulation FD releases in (start, end] (Exhibit 99 carries the outlook)."""
    return [f for f in filings if f.form in ("8-K", "8-K/A") and start < f.filing_date <= end
            and any(i in (f.items or "") for i in ("2.02", "7.01"))]


def release_targets(src, f: Filing) -> TargetResult:
    try:
        body = events._body(src, f)
    except Exception as exc:  # noqa: BLE001
        return TargetResult(unknowns=[Unknown("guidance_source_error", "실적·공정공시 본문을 읽지 못함", f"{f.accession}: {exc}"[:200])])
    paras = [p for p in re.split(r"(?<=[.!?])\s+(?=[A-Z•])", body) if len(p) > 40]
    return extract_targets(paras, f"{f.form} {f.filing_date}", f.url, f.filing_date)


def latest_before(src, filings: list[Filing], as_of: str, lookback_days: int = 200) -> tuple[list[VerifiedTarget], list[Unknown]]:
    """Targets stated in releases within ``lookback_days`` before ``as_of``: the newest statement per
    measure. A release that was not filed with the SEC (press release only) is not seen."""
    from datetime import date, timedelta

    start = (date.fromisoformat(as_of) - timedelta(days=lookback_days)).isoformat()
    found, unknowns = {}, []
    for f in reversed(releases(src, filings, start, as_of)):
        r = release_targets(src, f)
        unknowns += r.unknowns
        for vt in r.targets:
            found.setdefault(vt.target.metric, vt)  # one target per measure, the newest statement
    return list(found.values()), unknowns


def to_assumptions(targets: list[VerifiedTarget], recorded_at: str, start_id: int = 1,
                   threshold_source: str = "disclosed") -> list[Assumption]:
    out = []
    for i, vt in enumerate(targets, start_id):
        t = vt.target
        rng = f"{t.low_text}~{t.high_text}" if t.high_text else t.low_text
        out.append(Assumption(
            f"G{i}", f"{t.metric_text} 연 {rng} 성장 ({t.horizon_text or '기간 미기재'})", "guidance", f"guidance:{t.metric}",
            "above", Threshold(vt.low, threshold_source, vt.evidence.quote), horizon=t.horizon_text,
            source_quote=vt.evidence.quote, source_url=vt.evidence.url, recorded_at=recorded_at))
    return out


def same_measure(a: Assumption, vt: VerifiedTarget) -> bool:
    return a.indicator == f"guidance:{vt.target.metric}"
