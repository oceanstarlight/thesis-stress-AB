from riskprobe import lifecycle, lifecycle_report
from tests.test_audit import UA, make_http


def run(monkeypatch, ebitda, t0, end, **kw):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = make_http(ebitda, extra_8k=kw.pop("extra_8k", None))
    return lifecycle.run("ACME", t0, end, http, **kw)


def test_holding_review_flags_broken_assumption(monkeypatch):
    # debt 400: leverage 4x at T0 (FY2020), 10x after FY2022 (filed 2023-02-20)
    res = run(monkeypatch, {2020: 100, 2021: 100, 2022: 40}, "2021-06-30", "2023-06-30", rate_bp=0, ebitda_pct=0)
    assert res.verdict == "재검토 필요"
    lev = next(r for r in res.rows if "순차입금" in r.statement)
    assert lev.failure_type == "상황 변화" and lev.first_warning.startswith("2023-02-20")
    assert lev.at_t0.startswith("유지 · EBITDA 20% 감소까지 여유")
    md = lifecycle_report.render(res)
    assert "🔴 종합 판정: 재검토 필요" in md and "보유 점검 + 사후 감사" in md
    assert res.series and all(p["공개일"] >= "2021-06-30" for p in res.series)


def test_pre_investment_review_without_replay(monkeypatch):
    res = run(monkeypatch, {2020: 100, 2021: 100}, "2022-06-30", "2022-06-30", rate_bp=0, ebitda_pct=0)
    assert res.audit is None and res.verdict == "유지"
    assert "투자 전 검토" in lifecycle_report.render(res)


def test_scenario_alone_adds_one_point(monkeypatch):
    res = run(monkeypatch, {2020: 100, 2021: 100}, "2022-06-30", "2022-06-30", rate_bp=0, ebitda_pct=-30)
    assert res.score == 1.0 and res.verdict == "유지"
    assert any("시나리오" in r for r in res.reasons)


def test_recent_high_alert_means_caution(monkeypatch):
    acc = "0000000042-23-000099"
    res = run(monkeypatch, {2020: 100, 2021: 100, 2022: 100}, "2021-06-30", "2023-06-30", rate_bp=0, ebitda_pct=0,
              extra_8k=[(acc, "2023-05-15", "A wildfire damaged the main plant and operations stopped.")])
    assert res.verdict == "주의" and res.score == 2.0
    assert any("최근 90일 8-K 2023-05-15" in r for r in res.reasons)
    assert res.first_event.startswith("2023-05-15")


def test_score_components(monkeypatch):
    lev = lambda res: next(r for r in res.rows if "순차입금" in r.statement)  # noqa: E731
    # new breach, 100% beyond a default-rule cap, worse than T0: 3 x 0.7 + 1 = 3.1 -> 재검토 필요
    res = run(monkeypatch, {2020: 100, 2021: 100, 2022: 40}, "2021-06-30", "2023-06-30", rate_bp=0, ebitda_pct=0)
    assert round(lev(res).score, 2) == 3.1 and res.verdict == "재검토 필요"
    # already breached at T0 (8x) and not worse at the check date: 3 x 0.7 x 0.5 = 1.05 -> floor 주의
    res = run(monkeypatch, {2020: 50, 2021: 50}, "2021-06-30", "2022-06-30", rate_bp=0, ebitda_pct=0)
    assert round(lev(res).score, 2) == 1.05 and res.verdict == "주의"
    assert any("최소 '주의'" in r for r in res.reasons)
    # slight breach in a pre-investment review (AMT-like): 4.4x -> 5.26x? use 400/76 = 5.26x, 5% beyond: 1 x 0.7
    res = run(monkeypatch, {2020: 76, 2021: 76}, "2022-06-30", "2022-06-30", rate_bp=0, ebitda_pct=0)
    assert round(lev(res).score, 2) == 0.7 and res.verdict == "주의"


def test_hard_rules(monkeypatch):
    res = run(monkeypatch, {2020: 100, 2021: -10}, "2021-06-30", "2022-06-30", rate_bp=0, ebitda_pct=0)
    assert res.verdict == "재검토 필요" and any("EBITDA ≤ 0" in r for r in res.reasons)
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    http = make_http({2020: 100, 2021: 100})
    sub_url = [r for r in http.routes if r[0].endswith("CIK0000000042.json") and "submissions" in r[0]][0]
    rec = sub_url[3]["filings"]["recent"]
    for k, v in (("accessionNumber", "0000000042-22-000050"), ("form", "8-K"), ("filingDate", "2022-05-01"),
                 ("acceptanceDateTime", ""), ("reportDate", ""), ("items", "4.02"), ("primaryDocument", "doc.htm")):
        rec[k].append(v)
    res = lifecycle.run("ACME", "2021-06-30", "2022-06-30", http, rate_bp=0, ebitda_pct=0)
    assert res.verdict == "재검토 필요" and any("4.02" in r for r in res.reasons)
