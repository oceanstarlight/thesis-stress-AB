from riskprobe import config, indicators, watch, watch_report
from riskprobe.ledger import Assumption, Ledger, Threshold
from riskprobe.sources import rates
from tests.test_audit import UA, make_http

H15_CSV = '''"Series Description","10-year"
"Unit:","Percent:_Per_Year"
"Multiplier:","1"
"Currency:","NA"
"Unique Identifier: ","H15/H15/RIFLGFCY10_N.B"
"Time Period","RIFLGFCY10_N.B"
2021-06-30,1.50
2021-07-05,ND
2022-03-31,{late}
'''


def add_rates(http, earliest, until, sofr_end=0.30, ust_end=1.60):
    start = indicators._one_year_before(earliest)
    http.add(rates.SOFR, {"refRates": [{"effectiveDate": "2021-06-30", "percentRate": 0.05},
                                       {"effectiveDate": "2022-03-31", "percentRate": sofr_end}]})
    http.add(rates.H15.format(frm=rates._us(start), to=rates._us(until)), H15_CSV.format(late=ust_end).encode())
    return http


def ledger(t0="2021-06-30"):
    lg = Ledger("ACME", "ACME")
    lg.add(Assumption("A1", "순차입금/EBITDA 기준 이하", "financial", "net_debt_to_ebitda", "below",
                      Threshold(5.0, "default_rule"), path_template="ebitda_drop_to_leverage", recorded_at=t0))
    lg.add(Assumption("A2", "이자보상배율 기준 이상", "financial", "interest_coverage", "above",
                      Threshold(2.0, "default_rule"), path_template="ebitda_drop_to_coverage", recorded_at=t0))
    lg.add(Assumption("A3", "금리", "financial", "interest_coverage", "above", Threshold(2.0, "default_rule"),
                      path_template="rate_rise_to_coverage", recorded_at=t0, inputs={"floating_debt": 1000.0}))
    return lg


def test_parse_h15_skips_holidays():
    pts = rates._parse_h15(H15_CSV.format(late=1.6))
    assert pts == [("2021-06-30", 1.5), ("2022-03-31", 1.6)]
    assert rates._parse_h15("") is None


def test_watch_alerts_on_worse_state_event_and_rates(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    acc = "0000000042-22-000077"
    # EBITDA 100 (FY2020, T0) -> 50 (FY2021, filed 2022-02-20): leverage 4x -> 8x
    http = make_http({2020: 100, 2021: 50}, extra_8k=[(acc, "2022-03-01", "A wildfire destroyed the main facility.")])
    add_rates(http, "2021-06-30", "2022-03-31")
    res = watch.run([ledger()], "2021-06-30", "2022-03-31", http)
    kinds = [(a.kind, a.severity) for a in res.alerts]
    assert ("지표", "high") in kinds  # A1 supported -> weakened
    assert ("수시공시", "high") in kinds
    assert ("금리", "medium") in kinds  # SOFR +25bp
    assert res.rate_moves["sofr"][0] == 25.0
    st = res.entities[0]
    assert st.states == {"A1": "weakened", "A2": "supported"}
    # coverage now 50/10 = 5x; floor 2x -> EBITDA/2 - 10 = 15 absorbable on 1000 floating = 150bp, minus +25bp
    assert round(st.rate_headroom["A3"]) == 125
    md = watch_report.render(res)
    assert "감시 브리프" in md and "wildfire" not in md


def test_quiet_window_has_no_alerts(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = add_rates(make_http({2020: 100}), "2021-06-30", "2021-09-30", sofr_end=0.05, ust_end=1.5)
    res = watch.run([ledger()], "2021-06-30", "2021-09-30", http)
    assert res.alerts == []


def test_ledger_recorded_after_window_is_skipped(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = add_rates(make_http({2020: 100}), "2021-06-30", "2021-09-30")
    res = watch.run([ledger(t0="2022-01-01")], "2021-06-30", "2021-09-30", http)
    assert res.entities == [] and "watch_not_yet_recorded" in {u.code for u in res.unknowns}


def test_scenario_rate_and_ebitda_shock(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = make_http({2020: 100, 2021: 100})
    rows, _ = watch.scenario([ledger()], "2022-06-30", http, rate_bp=100, ebitda_pct=-20)
    by = {r.assumption: r for r in rows}
    assert "A3" not in by  # the rate path is the coverage ratio, shown once
    cov = by["A2"]
    assert cov.now == 10.0 and round(cov.after, 4) == round(80 / (10 + 10), 4) and cov.verdict == "유지"
    lev = by["A1"]
    assert lev.now == 4.0 and lev.after == 5.0 and lev.verdict == "근접"  # exactly at the cap
    rows, _ = watch.scenario([ledger()], "2022-06-30", http, ebitda_pct=-30)
    assert {r.assumption: r.verdict for r in rows}["A1"] == "초과"
    assert config.HEADROOM_NEAR["%"] == 15.0
