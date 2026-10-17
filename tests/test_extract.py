import pytest

from riskprobe import extract, text
from riskprobe.extract import Covenant, Customer, FilingExtraction, FloatingDebt, RateSensitivity, RiskItem

DOC_HTML = """<html><body><div><p>Item 7A. On a consolidated basis, of the Company's $28.8 billion of total gross debt
outstanding as of December 31, 2024, approximately $8.9 billion accrues interest at variable rates.</p>
<p>A hypothetical 100 basis point increase in interest rates would increase our annual interest expense by approximately $89 million.</p>
<p>A 10% increase in current interest rates would result in an additional $5.6 million of interest expense.</p>
<p>The revolving credit facility requires a maximum ratio of recourse debt to adjusted operating cash flow of 5.75 times.</p>
<p>Customer A accounted for approximately 22% of total revenues in 2024 and is our largest customer.</p>
<p>The weather was pleasant during the annual meeting held at the headquarters building last spring.</p>
<script>var x = "variable rate";</script></div></body></html>"""


def test_paragraphs_and_selection():
    paras = text.paragraphs(DOC_HTML)
    assert not any("var x" in p for p in paras)
    picked = text.select(paras, 10_000)
    assert len(picked) == 5 and not any("weather" in p for p in picked)
    assert text.select(paras, 150) and sum(map(len, text.select(paras, 150))) <= 150


@pytest.mark.parametrize("s,v", [("$8.9 billion", 8.9e9), ("$89 million", 89e6), ("$1,250", 1250.0), ("about 9", None)])
def test_parse_money(s, v):
    assert extract.parse_money(s) == v


def test_parse_bp_rejects_relative_percent():
    assert extract.parse_bp("100 basis points") == 100
    assert extract.parse_bp("1 percentage point") == 100
    assert extract.parse_bp("10%") is None


@pytest.mark.parametrize("s,v", [("5.75 times", 5.75), ("5.0 to 1.0", 5.0), ("3.5x", 3.5), ("4.00:1.00", 4.0)])
def test_parse_ratio(s, v):
    assert extract.parse_ratio(s) == v


def fake_output():
    q_float = ("On a consolidated basis, of the Company's $28.8 billion of total gross debt outstanding as of "
               "December 31, 2024, approximately $8.9 billion accrues interest at variable rates.")
    return FilingExtraction(
        risks=[RiskItem(category="floating_rate", summary_ko="변동금리 차입금이 많아 금리에 민감하다", quote=q_float),
               RiskItem(category="other", summary_ko="숫자 3이 들어간 요약", quote=q_float),
               RiskItem(category="other", summary_ko="지어낸 문장", quote="The company will default next year.")],
        rate_sensitivity=[
            RateSensitivity(change_text="100 basis point", impact_text="$89 million", measure="annual interest expense",
                            quote="A hypothetical 100 basis point increase in interest rates would increase our annual interest expense by approximately $89 million."),
            RateSensitivity(change_text="10%", impact_text="$5.6 million", measure="interest expense",
                            quote="A 10% increase in current interest rates would result in an additional $5.6 million of interest expense.")],
        floating_debt=[FloatingDebt(amount_text="$8.9 billion", share_text="", total_debt_text="$28.8 billion",
                                    as_of_text="December 31, 2024", quote=q_float)],
        covenants=[Covenant(metric="leverage", threshold_text="5.75 times", facility="revolving credit facility",
                            quote="The revolving credit facility requires a maximum ratio of recourse debt to adjusted operating cash flow of 5.75 times."),
                   Covenant(metric="interest_coverage", threshold_text="2.5 to 1.0", facility="term loan",
                            quote="The term loan requires interest coverage of 2.5 to 1.0.")],
        customers=[Customer(name="Customer A", share_text="22%",
                            quote="Customer A accounted for approximately 22% of total revenues in 2024 and is our largest customer.")],
    )


def test_extract_keeps_only_grounded_items(monkeypatch):
    monkeypatch.setattr("riskprobe.llm.structured_call", lambda schema, system, user: (fake_output(), None))
    paras = text.select(text.paragraphs(DOC_HTML), 10_000)
    res = extract.extract(paras, "ACME 10-K", "https://example.com/10k.htm", "2025-02-20")
    kinds = sorted(v.kind for v in res.items)
    assert kinds == ["covenant", "customer", "floating_debt", "rate_sensitivity", "risk"]
    assert res.of("floating_debt")[0].values == {"amount": 8.9e9, "total_debt": 28.8e9}
    assert res.of("rate_sensitivity")[0].values == {"bp": 100.0, "impact": 89e6}
    assert res.of("covenant")[0].values == {"threshold": 5.75}
    assert res.of("customer")[0].values == {"share_pct": 22.0}
    assert res.of("risk")[0].evidence.quote.startswith("On a consolidated basis")
    # rejected: digits in summary, invented quote, relative rate change, covenant not in text
    rejected = res.unknowns[0]
    assert rejected.code == "extract_rejected" and rejected.detail.count("::") == 4
    assert not any(ch.isdigit() for ch in rejected.message)


def test_extract_without_llm_is_an_unknown():
    res = extract.extract(["x" * 100], "ACME 10-K", "u", "2025-02-20")
    assert res.items == [] and [u.code for u in res.unknowns] == ["extract_unavailable"]
