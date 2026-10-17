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


def names_http():
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, {
        "0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "1": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
        "2": {"cik_str": 19617, "ticker": "JPM", "title": "JPMORGAN CHASE & CO"},
        "3": {"cik_str": 354707, "ticker": "HE", "title": "HAWAIIAN ELECTRIC INDUSTRIES INC"},
        "4": {"cik_str": 77, "ticker": "ALPH", "title": "Alphabetic Trust Capital LLC"},
    })
    return http


def test_search_by_name_ticker_and_cik(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    src = sec.SecSource(names_http())
    found = src.search("alphabet")
    assert [c.cik for c in found] == ["0001652044", "0000000077"]  # one row per company, exact name first
    assert found[0].tickers == ["GOOGL", "GOOG"] and found[0].label == "Alphabet Inc. (GOOGL, GOOG)"
    assert src.search("Hawaiian Electric")[0].ticker == "HE"
    assert src.search("jp morgan")[0].ticker == "JPM"
    assert src.search("goog")[0].ticker == "GOOGL"  # exact ticker beats name prefix
    assert src.cik_for("alphabet") == "0001652044"
    assert src.cik_for("1652044") == "0001652044"
    assert src.search("zzzz") == [] and src.cik_for("zzzz") is None


def test_profile_warns_for_foreign_filers_and_financials():
    foreign = sec.profile_warnings("3711", "Motor Vehicles", {"20-F", "6-K"})
    bank = sec.profile_warnings("6021", "National Commercial Banks", {"10-K", "10-Q", "8-K"})
    reit = sec.profile_warnings("6798", "Real Estate Investment Trusts", {"10-K", "10-Q"})
    assert [u.code for u in foreign] == ["sec_foreign_filer"]
    assert [u.code for u in bank] == ["sec_financial_sector"]
    assert reit == []
    assert not any(ch.isdigit() for u in foreign + bank for ch in u.message)


def test_load_adds_profile_warnings(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = make_http()
    sub = http.routes[1][3]
    sub.update(sic="6021", sicDescription="National Commercial Banks")
    res = sec.SecSource(http).load("ABC")
    assert "sec_financial_sector" in {u.code for u in res.unknowns}
    assert sec.SecSource(http).profile("42").warnings[0].code == "sec_financial_sector"
