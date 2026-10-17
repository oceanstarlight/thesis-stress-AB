import json

from riskprobe import audit, audit_report, events
from riskprobe.ledger import Assumption, Ledger, Threshold
from riskprobe.sources import sec
from riskprobe.sources.sec import Filing
from tests import fakes

CIK = "0000000042"
UA = "riskprobe test test@example.com"
ARCH = "https://www.sec.gov/Archives/edgar/data/42/{acc}/"


def yr(y, val, accn, filed):
    return fakes.fact_row(val, f"{y}-01-01", f"{y}-12-31", accn, filed, "10-K")


def make_http(ebitda_by_year: dict[int, float], debt=400.0, cash=0.0, extra_8k=None):
    """One 10-K per year; operating income = EBITDA, no D&A tag needed (EBITDA = OI + D&A, D&A = 0)."""
    concepts = {"Revenues": [], "OperatingIncomeLoss": [], "DepreciationAndAmortization": [],
                "InterestExpense": [], "LongTermDebt": [], "CashAndCashEquivalentsAtCarryingValue": []}
    filings = []
    for y, e in sorted(ebitda_by_year.items()):
        accn, filed = f"0000000042-{str(y + 1)[2:]}-000001", f"{y + 1}-02-20"
        concepts["Revenues"].append(yr(y, 1000, accn, filed))
        concepts["OperatingIncomeLoss"].append(yr(y, e, accn, filed))
        concepts["DepreciationAndAmortization"].append(yr(y, 0, accn, filed))
        concepts["InterestExpense"].append(yr(y, 10, accn, filed))
        concepts["LongTermDebt"].append(fakes.fact_row(debt, None, f"{y}-12-31", accn, filed, "10-K"))
        concepts["CashAndCashEquivalentsAtCarryingValue"].append(fakes.fact_row(cash, None, f"{y}-12-31", accn, filed, "10-K"))
        filings.append((accn, "10-K", filed))
    for accn, filed, _ in extra_8k or []:
        filings.append((accn, "8-K", filed))
    sub = fakes.submissions("ACME", filings)
    rec = sub["filings"]["recent"]
    rec["reportDate"] = [f"{int(f[2][:4]) - 1}-12-31" if f[1] == "10-K" else "" for f in filings]
    rec["items"] = ["" if f[1] == "10-K" else "8.01" for f in filings]
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, {"0": {"cik_str": 42, "ticker": "ACME", "title": "ACME"}})
    http.add(sec.SUBMISSIONS.format(cik=CIK), sub)
    http.add(sec.COMPANY_FACTS.format(cik=CIK), fakes.company_facts("ACME", concepts))
    for accn, _, body in extra_8k or []:
        base = ARCH.format(acc=accn.replace("-", ""))
        http.add(base + "doc.htm", f"<p>{body}</p>".encode())
        http.add(base + "index.json", {"directory": {"item": [{"name": "doc.htm"}, {"name": "ex99-1.htm"}]}})
        http.add(base + "ex99-1.htm", b"<p>Investor update on operations and outlook for the coming year ahead.</p>")
    return http


def ledger(t0="2021-06-30", cap=5.0):
    lg = Ledger("ACME", "ACME")
    lg.add(Assumption("A1", "순차입금/EBITDA가 기준 이하로 유지된다", "financial", "net_debt_to_ebitda", "below",
                      Threshold(cap, "default_rule"), path_template="ebitda_drop_to_leverage", recorded_at=t0))
    return lg


def run(http, lg, end="2025-06-30", monkeypatch=None):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    return audit.run(lg, end, http)


def test_situation_change_and_first_warning(monkeypatch):
    # leverage 400/100 = 4x at T0 (FY2020), then EBITDA falls: 2021 4x, 2022 8x, 2023 10x
    http = make_http({2020: 100, 2021: 100, 2022: 50, 2023: 40})
    res = run(http, ledger(), monkeypatch=monkeypatch)
    aa = res.audits[0]
    assert [e.status for e in aa.evaluations] == ["supported", "supported", "weakened", "weakened"]
    assert aa.evaluations[0].is_baseline and aa.evaluations[0].period_end == "2020-12-31"
    assert aa.first_warning.date == "2023-02-20"
    assert aa.failure_type == "상황 변화"
    assert len(aa.assumption.history) == 4


def test_temporary_dip(monkeypatch):
    res = run(make_http({2020: 100, 2021: 50, 2022: 100}), ledger(), monkeypatch=monkeypatch)
    assert res.audits[0].failure_type == "일시적 흔들림"


def test_missed_signal_when_broken_at_t0(monkeypatch):
    res = run(make_http({2020: 50, 2021: 100}), ledger(), monkeypatch=monkeypatch)
    aa = res.audits[0]
    assert aa.failure_type == "신호 놓침" and aa.first_warning.is_baseline


def test_negative_ebitda_is_weakened_not_insufficient(monkeypatch):
    res = run(make_http({2020: 100, 2021: -20}), ledger(), monkeypatch=monkeypatch)
    assert [e.status for e in res.audits[0].evaluations] == ["supported", "weakened"]
    assert "EBITDA ≤ 0" in audit_report.render(res)


def test_held(monkeypatch):
    res = run(make_http({2020: 100, 2021: 110, 2022: 120}), ledger(), monkeypatch=monkeypatch)
    assert res.audits[0].failure_type == "가정 유지"


def test_fragility_flag(monkeypatch):
    # Before T0 EBITDA fell 60% in a year (2019 vs 2018); margin at T0 is 1 - 4/5 = 20%.
    res = run(make_http({2017: 250, 2018: 250, 2019: 100, 2020: 100, 2021: 100}), ledger(), monkeypatch=monkeypatch)
    aa = res.audits[0]
    assert aa.fragile is True and any("가정 무리 신호" in r for r in aa.reasons)


def test_no_future_data_in_any_evaluation(monkeypatch):
    res = run(make_http({2020: 100, 2021: 100, 2022: 50, 2023: 40}), ledger(), monkeypatch=monkeypatch)
    for e in res.audits[0].evaluations:
        assert e.period_end < e.date  # each state uses only reports filed by that date


def test_event_before_financial_warning(monkeypatch):
    acc = "0000000042-22-000077"
    http = make_http({2020: 100, 2021: 100, 2022: 50}, extra_8k=[(acc, "2022-03-01", "A wildfire damaged our main plant.")])
    res = run(http, ledger(), monkeypatch=monkeypatch)
    ev = [e for e in res.events if e.filing.accession == acc][0]
    assert ev.severity == "high" and "재해·사고" in ev.labels and "wildfire" in ev.matched[0]
    md = audit_report.render(res)
    assert "일 먼저" in md and "가정의 첫 경고" in md


def test_event_item_rules():
    f = Filing("a", "8-K", "2024-01-01", "", "", "2.04,9.01", "u")
    assert events.tag(f).severity == "high"
    f = Filing("a", "8-K", "2024-01-01", "", "", "7.01,9.01", "u")
    assert events.tag(f).severity == "skip"
    assert events.tag(f, "The board decided to suspend the quarterly dividend.").labels == ["배당 축소·중단"]


def test_all_insufficient_is_undecidable_even_with_alerts(monkeypatch):
    lg = Ledger("ACME", "ACME")
    lg.add(Assumption("A1", "x", "financial", "short_term_debt_share", "below", Threshold(30.0, "user"), recorded_at="2021-06-30"))
    res = run(make_http({2020: 100, 2021: 100}), lg, monkeypatch=monkeypatch)
    assert res.audits[0].failure_type == "판단 불가"


def test_rate_path_assumption_is_not_replayed(monkeypatch):
    lg = ledger()
    lg.add(Assumption("A2", "금리", "financial", "interest_coverage", "above", Threshold(2.0, "default_rule"),
                      path_template="rate_rise_to_coverage", recorded_at="2021-06-30"))
    res = run(make_http({2020: 100, 2021: 100}), lg, monkeypatch=monkeypatch)
    assert [aa.assumption.id for aa in res.audits] == ["A1"]
    assert "audit_rate_path_skipped" in {u.code for u in res.unknowns}
