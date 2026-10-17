"""Risk facts from filing text: the LLM proposes, code verifies and parses.

The model reads keyword-selected paragraphs of an annual report and returns risk items, the
company's own interest rate sensitivity, floating rate debt, covenant thresholds and customer
concentration, each with a verbatim quote. Code keeps an item only if the quote is in the
filing and the value text is inside the quote, then parses numbers itself. The model never
supplies a number that code did not read out of the quoted text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from riskprobe import llm
from riskprobe.models import Evidence, Unknown
from riskprobe.text import squash

Category = Literal["debt_structure", "floating_rate", "refinancing", "covenant", "liquidity", "credit_rating",
                   "customer_concentration", "contract", "fx", "regulatory", "operations", "other"]


class RiskItem(BaseModel):
    category: Category
    summary_ko: str = Field(description="One Korean sentence stating the risk, no figures")
    quote: str = Field(description="Verbatim sentence from the text that states the risk")


class RateSensitivity(BaseModel):
    change_text: str = Field(description="Rate change exactly as written, e.g. '100 basis points'")
    impact_text: str = Field(description="Money impact exactly as written, e.g. '$25 million'")
    measure: str = Field(description="What changes, as written, e.g. 'interest expense' or 'pre-tax earnings'")
    quote: str = Field(description="Verbatim sentence containing change_text and impact_text")


class FloatingDebt(BaseModel):
    amount_text: str = Field(description="Floating or variable rate debt amount exactly as written, or empty")
    share_text: str = Field(description="Share of total debt that is floating exactly as written, e.g. '15%', or empty")
    total_debt_text: str = Field(description="Total debt amount if the same sentence states it, exactly as written, or empty")
    as_of_text: str = Field(description="Date the sentence refers to, exactly as written, or empty")
    quote: str = Field(description="Verbatim sentence containing the amount or share")


class Covenant(BaseModel):
    metric: Literal["leverage", "interest_coverage", "other"]
    threshold_text: str = Field(description="Required level exactly as written, e.g. '5.0 to 1.0' or '3.5x'")
    facility: str = Field(description="Which agreement, as written, e.g. 'revolving credit facility'")
    quote: str = Field(description="Verbatim sentence containing threshold_text")


class Customer(BaseModel):
    name: str = Field(description="Customer or counterparty exactly as written")
    share_text: str = Field(description="Share of revenue exactly as written, e.g. '22%'")
    quote: str = Field(description="Verbatim sentence containing name and share_text")


class FilingExtraction(BaseModel):
    risks: list[RiskItem]
    rate_sensitivity: list[RateSensitivity]
    floating_debt: list[FloatingDebt]
    covenants: list[Covenant]
    customers: list[Customer]


SYSTEM = (
    "You read excerpts of a company's annual report for a credit risk review. Extract only what "
    "the text states explicitly about the reporting company and its consolidated debt: up to eight "
    "material risks (debt structure, floating rates, refinancing, covenants, liquidity, credit "
    "ratings, customer concentration, contracts, currency, regulation); the company's disclosed "
    "sensitivity of interest expense or earnings to a change in interest rates; the amount or share "
    "of floating or variable rate debt; financial covenant thresholds (leverage or interest "
    "coverage); customers that account for a stated share of revenue. Copy every quote, number "
    "and name verbatim from the text; never compute, convert, round or infer a figure. Write "
    "summary_ko in Korean without any digits. Return empty lists when the text states nothing."
)

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|m)?\b", re.I)
_SCALE = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, None: 1.0}
_BP = re.compile(r"(\d+(?:\.\d+)?)\s*(?:basis points?|bps?)\b", re.I)
_PP = re.compile(r"(\d+(?:\.\d+)?)\s*(?:percentage points?|%\s*point)", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", re.I)
_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x\b|times\b|to\s*1(?:\.0+)?\b|:\s*1(?:\.0+)?\b)", re.I)


def parse_money(s: str) -> float | None:
    m = _MONEY.search(s or "")
    if not m:
        return None
    return float(m.group(1).replace(",", "")) * _SCALE[(m.group(2) or "").lower() or None]


def parse_bp(s: str) -> float | None:
    """Absolute rate change in basis points. A bare '10%' is ambiguous (relative or absolute)
    and is not accepted."""
    m = _BP.search(s or "")
    if m:
        return float(m.group(1))
    m = _PP.search(s or "")
    return float(m.group(1)) * 100 if m else None


def parse_pct(s: str) -> float | None:
    m = _PCT.search(s or "")
    return float(m.group(1)) if m else None


def parse_ratio(s: str) -> float | None:
    m = _RATIO.search(s or "")
    return float(m.group(1)) if m else None


@dataclass
class Verified:
    kind: str  # risk | rate_sensitivity | floating_debt | covenant | customer
    item: BaseModel
    evidence: Evidence
    values: dict[str, float] = field(default_factory=dict)  # parsed by code from the quote


@dataclass
class ExtractionResult:
    items: list[Verified] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    chars_sent: int = 0

    def of(self, kind: str) -> list[Verified]:
        return [v for v in self.items if v.kind == kind]


def _in(needle: str, hay: str) -> bool:
    return bool(needle) and squash(needle) in squash(hay)


def verify(kind: str, item: BaseModel, doc: str) -> tuple[dict[str, float], list[str]]:
    """(parsed values, problems). Empty problems means the item is grounded in the text."""
    problems, values = [], {}
    quote = item.quote
    if not _in(quote, doc):
        problems.append("quote not found in filing")
    if kind == "rate_sensitivity":
        for t in (item.change_text, item.impact_text):
            if not _in(t, quote):
                problems.append(f"'{t}' not inside quote")
        bp, money = parse_bp(item.change_text), parse_money(item.impact_text)
        if bp is None:
            problems.append("rate change is not stated in basis or percentage points")
        if money is None:
            problems.append("impact is not a money amount")
        if bp and money:
            values = {"bp": bp, "impact": money}
    elif kind == "floating_debt":
        texts = [t for t in (item.amount_text, item.share_text, item.total_debt_text, item.as_of_text) if t]
        if not texts:
            problems.append("no amount or share")
        for t in texts:
            if not _in(t, quote):
                problems.append(f"'{t}' not inside quote")
        if item.amount_text and parse_money(item.amount_text) is not None:
            values["amount"] = parse_money(item.amount_text)
        if item.share_text and parse_pct(item.share_text) is not None:
            values["share_pct"] = parse_pct(item.share_text)
        if item.total_debt_text and parse_money(item.total_debt_text) is not None:
            values["total_debt"] = parse_money(item.total_debt_text)
        if not ({"amount", "share_pct"} & set(values)):
            problems.append("no parsable amount or share")
    elif kind == "covenant":
        if not _in(item.threshold_text, quote):
            problems.append("threshold not inside quote")
        r = parse_ratio(item.threshold_text)
        if r is None:
            problems.append("threshold is not a ratio")
        else:
            values["threshold"] = r
    elif kind == "customer":
        for t in (item.name, item.share_text):
            if not _in(t, quote):
                problems.append(f"'{t}' not inside quote")
        p = parse_pct(item.share_text)
        if p is None:
            problems.append("share is not a percentage")
        else:
            values["share_pct"] = p
    elif kind == "risk":
        if any(ch.isdigit() for ch in item.summary_ko):
            problems.append("summary contains digits")
    return values, problems


def extract(paragraphs: list[str], title: str, url: str, published_at: str) -> ExtractionResult:
    res = ExtractionResult()
    doc = "\n".join(paragraphs)
    res.chars_sent = len(doc)
    out, err = llm.structured_call(FilingExtraction, SYSTEM, f"REPORT: {title}\n\nEXCERPTS:\n{doc}")
    if out is None:
        res.unknowns.append(Unknown("extract_unavailable", "공시 문서 추출을 실행하지 못해 문서 기반 위험 요인과 기준값을 쓰지 않음", err or ""))
        return res
    groups = {"risk": out.risks, "rate_sensitivity": out.rate_sensitivity, "floating_debt": out.floating_debt,
              "covenant": out.covenants, "customer": out.customers}
    rejected = []
    for kind, items in groups.items():
        for it in items:
            values, problems = verify(kind, it, doc)
            if problems:
                rejected.append(f"{kind}: {problems} :: {it.quote[:80]}")
                continue
            ev = Evidence("sec", title, url, published_at=published_at, locator=kind, quote=it.quote)
            res.items.append(Verified(kind, it, ev, values))
    if not res.items and not rejected:
        res.unknowns.append(Unknown("extract_empty", "연차보고서 발췌문에서 추출할 위험 요인이나 기준값을 찾지 못함"))
    if rejected:
        res.unknowns.append(Unknown("extract_rejected", "원문에서 확인되지 않거나 수치를 읽을 수 없는 추출 결과를 버림",
                                    " | ".join(rejected)[:2000]))
    return res
