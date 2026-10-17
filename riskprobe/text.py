"""Filing HTML to plain paragraphs, and keyword selection of the paragraphs worth reading.

Annual reports run to hundreds of thousands of characters. Code keeps only paragraphs about
debt structure, rates, covenants, liquidity and concentration before any model sees the text,
which cuts the prompt to about a tenth and keeps the extraction cheap.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "td", "table"}
_BREAK = "\x00"  # block boundary; raw newlines in the source are only whitespace
_HIDDEN = {"script", "style", "ix:header"}

RISK_KEYWORDS = re.compile(
    r"variable[- ]rate|floating[- ]rate|SOFR|LIBOR|interest rate swap|basis points?|"
    r"hypothetical (?:\d+|one|ten)|(?:increase|change|rise) in (?:current |market )?interest rates|"
    r"covenant|leverage ratio|coverage ratio|refinanc|maturit|"
    r"credit rating|downgrade|liquidity|concentration|% of (?:our )?(?:total |consolidated )?revenues?|"
    r"largest customer|significant customer|power purchase agreement|non-recourse|recourse debt|"
    r"foreign currenc|going concern|waiver|amendment to (?:the |our )?credit",
    re.IGNORECASE,
)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN:
            self.skip += 1
        if tag in _BLOCK:
            self.out.append(_BREAK)

    def handle_endtag(self, tag):
        if tag in _HIDDEN and self.skip:
            self.skip -= 1
        if tag in _BLOCK:
            self.out.append(_BREAK)

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def paragraphs(doc_html: str, min_len: int = 60) -> list[str]:
    p = _Text()
    p.feed(doc_html)
    text = html.unescape("".join(p.out)).replace("\xa0", " ")
    out = []
    for block in text.split(_BREAK):
        block = re.sub(r"\s+", " ", block).strip()
        if len(block) >= min_len:
            out.append(block)
    return out


def select(paras: list[str], max_chars: int, pattern: re.Pattern = RISK_KEYWORDS) -> list[str]:
    """Paragraphs matching ``pattern`` in document order, deduplicated, up to ``max_chars``.
    Paragraphs with more keyword hits are kept first when the budget runs out."""
    seen, hits = set(), []
    for i, p in enumerate(paras):
        n = len(pattern.findall(p))
        if n and p not in seen:
            seen.add(p)
            hits.append((i, n, p))
    chosen, used = [], 0
    for i, _, p in sorted(hits, key=lambda h: (-h[1], h[0])):
        if used + len(p) > max_chars:
            continue
        chosen.append((i, p))
        used += len(p)
    return [p for _, p in sorted(chosen)]


def squash(s: str) -> str:
    """Normalize for quote matching: whitespace, quotes, dashes and case."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()
