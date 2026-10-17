from riskprobe import pit
from riskprobe.sources import sec
from tests import fakes

CIK = "0000000042"
UA = "riskprobe test test@example.com"


def make_http():
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, {"0": {"cik_str": 42, "ticker": "ABC", "title": "ABC Corp"}})
    http.add(sec.SUBMISSIONS.format(cik=CIK), fakes.submissions("ABC Corp", [
        ("0000000042-24-000001", "10-Q", "2024-05-01"), ("0000000042-25-000009", "10-K/A", "2025-08-01")]))
    http.add(sec.COMPANY_FACTS.format(cik=CIK), fakes.company_facts("ABC Corp", {"Revenues": [
        fakes.fact_row(100, "2024-01-01", "2024-03-31", "0000000042-24-000001", "2024-05-01"),
        fakes.fact_row(90, "2024-01-01", "2024-03-31", "0000000042-25-000009", "2025-08-01", form="10-K/A"),
    ]}))
    return http


def test_load_by_ticker_builds_point_in_time_facts(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    res = sec.SecSource(make_http()).load("abc")
    assert res.name == "ABC Corp"
    assert len(res.facts) == 2 and len(res.filings) == 2
    assert res.facts[0].concept == "us-gaap:Revenues"
    assert res.facts[0].url == "https://www.sec.gov/Archives/edgar/data/42/000000004224000001/"
    assert pit.snapshot(res.facts, "2025-01-01").get("us-gaap:Revenues", "2024-01-01", "2024-03-31").value == 100
    assert pit.snapshot(res.facts, "2025-08-01").get("us-gaap:Revenues", "2024-01-01", "2024-03-31").value == 90
    assert {u.code for u in res.unknowns} == {"sec_press_release_gap", "sec_coverage_start"}


def test_without_user_agent_nothing_is_fetched():
    http = make_http()
    res = sec.SecSource(http).load("ABC")
    assert res.facts == [] and http.calls == []
    assert [u.code for u in res.unknowns] == ["sec_unavailable"]


def test_unknown_ticker(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    res = sec.SecSource(make_http()).load("ZZZ")
    assert [u.code for u in res.unknowns] == ["sec_not_found"]


def test_fetch_failure_becomes_unknown(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, b"not json")  # unparseable response
    res = sec.SecSource(http).load("ABC")
    assert [u.code for u in res.unknowns] == ["sec_error"]
    assert not any(ch.isdigit() for u in res.unknowns for ch in u.message)
