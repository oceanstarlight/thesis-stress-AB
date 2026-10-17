"""Current reports (8-K) as timeline events, tagged by rule (no LLM).

SEC Form 8-K items are structured, so most of the meaning comes from the item numbers. Items
7.01 (Regulation FD) and 8.01 (other events) carry the news that has no item of its own
(a wildfire, a lawsuit, a rating action), so their text and their Exhibit 99 attachments
(where the news usually is) are scanned with keyword rules. Tags
are signals to look at, never a statement of cause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from riskprobe import text
from riskprobe.models import Unknown
from riskprobe.sources.sec import Filing

# item -> (label, severity). severity: high | medium | info | skip
ITEMS = {
    "1.01": ("중요 계약 체결", "info"), "1.02": ("중요 계약 해지", "medium"), "1.03": ("파산·법정관리", "high"),
    "1.05": ("중대 사이버 보안 사고", "medium"), "2.01": ("자산 인수·처분 완료", "info"), "2.02": ("실적 발표", "skip"),
    "2.03": ("차입·채무 발생", "info"), "2.04": ("채무 조기상환 사유 발생", "high"), "2.05": ("구조조정 비용", "medium"),
    "2.06": ("중대한 손상차손", "medium"), "3.01": ("상장폐지·상장요건 미달 통지", "high"), "3.02": ("비공개 지분 발행", "info"),
    "3.03": ("주주 권리 변경", "info"), "4.01": ("감사인 변경", "medium"), "4.02": ("과거 재무제표 신뢰 불가(재작성)", "high"),
    "5.01": ("지배권 변경", "medium"), "5.02": ("임원·이사 변동", "info"), "5.03": ("정관 변경", "skip"),
    "5.07": ("주주총회 결과", "skip"), "7.01": ("공정공시", "skip"), "8.01": ("기타 사건", "info"), "9.01": ("첨부", "skip"),
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2, "skip": 3}

# Keyword rules for 7.01 / 8.01 text. (tag, label, severity, pattern)
KEYWORDS = [
    ("disaster", "재해·사고", "high", r"wildfire|hurricane|earthquake|flood(?:ing)?\b|explosion|catastroph"),
    ("litigation", "소송·조사", "medium", r"lawsuit|litigation|class action|subpoena|investigation|settlement agreement"),
    ("rating", "신용등급", "medium", r"downgrade|credit rating|rating agenc|Moody's|S&P Global Ratings|Fitch"),
    ("dividend", "배당 축소·중단", "high", r"dividend[^.]{0,80}(?:suspen|eliminat|reduc|cut)|(?:suspen|eliminat|reduc)[^.]{0,40}dividend"),
    ("liquidity", "유동성·약정", "high", r"going concern|waiver|forbearance|amend(?:ment|ed)[^.]{0,60}credit (?:agreement|facility)"),
    ("strategic", "전략적 검토·매각", "medium", r"strategic (?:review|alternatives)|definitive agreement to sell|divestiture"),
]
_KW = [(t, l, s, re.compile(p, re.I)) for t, l, s, p in KEYWORDS]


@dataclass
class Event:
    date: str
    filing: Filing
    labels: list[str] = field(default_factory=list)
    severity: str = "info"
    matched: list[str] = field(default_factory=list)  # keyword snippets, verbatim


def tag(filing: Filing, doc_text: str = "") -> Event:
    ev = Event(filing.filing_date, filing)
    sev = "skip"
    for item in [i.strip() for i in (filing.items or "").split(",") if i.strip()]:
        label, s = ITEMS.get(item, (f"항목 {item}", "info"))
        if s != "skip":
            ev.labels.append(label)
        sev = min(sev, s, key=SEVERITY_ORDER.get)
    for _, label, s, pat in _KW:
        m = pat.search(doc_text)
        if m:
            ev.labels.append(label)
            ev.matched.append(doc_text[max(0, m.start() - 80): m.end() + 80].strip())
            sev = min(sev, s, key=SEVERITY_ORDER.get)
    ev.severity = sev
    return ev


_EX99 = re.compile(r"ex(?:hibit)?[-_]?99[\w.-]*\.(?:htm|html|txt)$", re.I)
MAX_EXHIBITS = 2


def _body(src, f: Filing) -> str:
    """Primary document text plus up to two Exhibit 99 documents."""
    base = f.url.rsplit("/", 1)[0] if f.url.endswith((".htm", ".html", ".txt")) else f.url.rstrip("/")
    parts = [" ".join(text.paragraphs(src._get(f.url).text, min_len=20))]
    names = [x["name"] for x in src._get(f"{base}/index.json").json()["directory"]["item"]]
    for name in [n for n in names if _EX99.search(n)][:MAX_EXHIBITS]:
        parts.append(" ".join(text.paragraphs(src._get(f"{base}/{name}").text, min_len=20)))
    return " ".join(parts)[:80_000]


def scan(src, filings: list[Filing], start: str, end: str) -> tuple[list[Event], list[Unknown]]:
    """Tagged 8-K events filed in (start, end]. Text is read only for items 7.01 and 8.01."""
    events, failed = [], []
    for f in filings:
        if f.form not in ("8-K", "8-K/A") or not (start < f.filing_date <= end):
            continue
        body = ""
        if any(i in (f.items or "") for i in ("7.01", "8.01")):
            try:
                body = _body(src, f)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{f.accession}: {type(exc).__name__}")
        ev = tag(f, body)
        if ev.severity != "skip":
            events.append(ev)
    unknowns = []
    if failed:
        unknowns.append(Unknown("event_text_unavailable", "일부 수시공시 본문을 읽지 못해 항목 번호로만 분류함", "; ".join(failed)[:500]))
    return events, unknowns
