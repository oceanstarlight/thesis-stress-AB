from riskprobe import probe, report
from riskprobe.sources import sec
from tests import fakes
from tests.test_extract import DOC_HTML, fake_output

CIK = "0000000042"
UA = "riskprobe test test@example.com"
TENK = "https://www.sec.gov/Archives/edgar/data/42/000000004225000002/doc.htm"


def q(start, end, val, accn, filed, form="10-Q"):
    return fakes.fact_row(val, start, end, accn, filed, form)


def make_http():
    A1, A2, A3 = "0000000042-24-000001", "0000000042-25-000002", "0000000042-25-000003"
    concepts = {
        "Revenues": [q("2024-01-01", "2024-03-31", 100, A1, "2024-05-01"), q("2024-01-01", "2024-12-31", 440, A2, "2025-02-20", "10-K"),
                     q("2025-01-01", "2025-03-31", 110, A3, "2025-05-01"), q("2024-01-01", "2024-03-31", 100, A3, "2025-05-01")],
        "OperatingIncomeLoss": [q("2024-01-01", "2024-12-31", 120, A2, "2025-02-20", "10-K"),
                                q("2025-01-01", "2025-03-31", 30, A3, "2025-05-01"), q("2024-01-01", "2024-03-31", 30, A3, "2025-05-01")],
        "DepreciationAndAmortization": [q("2024-01-01", "2024-12-31", 40, A2, "2025-02-20", "10-K"),
                                        q("2025-01-01", "2025-03-31", 10, A3, "2025-05-01"), q("2024-01-01", "2024-03-31", 10, A3, "2025-05-01")],
        "InterestExpense": [q("2024-01-01", "2024-12-31", 40, A2, "2025-02-20", "10-K"),
                            q("2025-01-01", "2025-03-31", 10, A3, "2025-05-01"), q("2024-01-01", "2024-03-31", 10, A3, "2025-05-01")],
        "CashAndCashEquivalentsAtCarryingValue": [q(None, "2025-03-31", 50, A3, "2025-05-01")],
    }
    filings = [(A1, "10-Q", "2024-05-01"), (A2, "10-K", "2025-02-20"), (A3, "10-Q", "2025-05-01")]
    sub = fakes.submissions("ACME", filings)
    sub["filings"]["recent"]["reportDate"] = ["2024-03-31", "2024-12-31", "2025-03-31"]
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, {"0": {"cik_str": 42, "ticker": "ACME", "title": "ACME"}})
    http.add(sec.SUBMISSIONS.format(cik=CIK), sub)
    http.add(sec.COMPANY_FACTS.format(cik=CIK), fakes.company_facts("ACME", concepts))
    http.add(TENK, DOC_HTML.encode())
    return http


def test_probe_end_to_end(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    monkeypatch.setattr("riskprobe.llm.structured_call", lambda schema, system, user: (fake_output(), None))
    res = probe.run("ACME", "2025-06-30", make_http())
    assert res.anchor == "2025-03-31" and res.filing.form == "10-K"
    by = {(s.result.template, s.ebitda_basis, s.threshold_label): s for s in res.scenarios}
    cov = by[("ebitda_drop_to_coverage", "공시 EBITDA", "기본 규칙")].result
    assert cov.current == 160 / 40 and round(cov.shock, 6) == 50.0
    # Disclosed covenant computed as its own labeled scenario, not replacing the default rule.
    assert ("ebitda_drop_to_coverage", "공시 EBITDA", "공시 약정 (정의 차이 주의)") not in by  # that covenant was rejected
    lev = by[("ebitda_drop_to_leverage", "공시 EBITDA", "공시 약정 (정의 차이 주의)")]
    assert lev.result.threshold.value == 5.75 and lev.result.threshold.source == "disclosed"
    # Total debt from the filing sentence, floating debt from the same disclosure.
    assert any("연차보고서 문장의 금액" in n for n in lev.input_notes)
    rate = by[("rate_rise_to_coverage", "공시 EBITDA", "기본 규칙")]
    assert rate.result.inputs["floating_debt"] == 8.9e9 and rate.input_notes == ["변동금리 차입금: 연차보고서 공시 금액"]
    assert [a.id for a in res.ledger.assumptions][-1].startswith("A")
    assert any("Customer A" in a.statement for a in res.ledger.assumptions)


def test_probe_never_reads_filings_after_as_of(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    res = probe.run("ACME", "2025-01-31", make_http())
    assert res.filing is None and res.anchor == "2024-03-31"
    assert {u.code for u in res.unknowns} >= {"probe_no_annual_report"}


def test_report_drops_llm_reading_that_writes_numbers(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    monkeypatch.setattr("riskprobe.llm.structured_call", lambda schema, system, user: (fake_output(), None))
    res = probe.run("ACME", "2025-06-30", make_http())

    def bad(schema, system, user):
        return report.Reading(links_ko=["변동금리 차입금이 EBITDA의 50%를 넘는다"], checks_ko=["확인"]), None

    monkeypatch.setattr("riskprobe.llm.structured_call", bad)
    md = report.render(res)
    assert "50%를 넘는다" not in md and "LLM 해석을 쓰지 않음" in md
    assert "조건부 계산(예측 아님)" in md

    def good(schema, system, user):
        return report.Reading(links_ko=["변동금리 차입금 비중이 금리 경로를 움직인다"], checks_ko=["헤지 비율은 얼마인가"]), None

    monkeypatch.setattr("riskprobe.llm.structured_call", good)
    md = report.render(res)
    assert "변동금리 차입금 비중이 금리 경로를 움직인다" in md and "헤지 비율은 얼마인가" in md


def test_conclusion_is_code_written(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    res = probe.run("ACME", "2025-06-30", make_http())
    lines = report.conclusion(res)
    assert any("EBITDA가 50.0% 줄면 기준 도달 → 여유 충분" in x for x in lines)


def test_audit_and_fill():
    facts = {"s1_shock": "12.2%"}
    assert report.audit("충격 [[s1_shock]]에서 기준에 닿는다", facts) == []
    assert report.audit("충격 [[s1_shock]]%에서", facts) == ["unit appended to a placeholder"]
    assert report.audit("부도 확률이 높다", facts) == ["probability or trade recommendation wording"]
    assert report.audit("두 배로 늘어난다", {}) == ["number words outside placeholders"]
    assert report.fill("[[s1_shock]]", facts) == "12.2%"


def test_huge_rate_shock_is_shown_as_insensitive():
    from riskprobe import reverse
    from riskprobe.ledger import Threshold
    r = reverse.rate_rise_to_coverage(6000.0, 1000.0, 1000.0, Threshold(2.0, "user"))
    assert r.beyond_cap and "사실상 둔감" in report.shock_text(r)
