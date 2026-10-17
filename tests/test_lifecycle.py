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


def test_scenario_break_means_caution(monkeypatch):
    res = run(monkeypatch, {2020: 100, 2021: 100}, "2022-06-30", "2022-06-30", rate_bp=0, ebitda_pct=-30)
    assert res.verdict == "주의"
    assert any("시나리오" in r for r in res.reasons)


def test_recent_high_alert_means_caution(monkeypatch):
    acc = "0000000042-23-000099"
    res = run(monkeypatch, {2020: 100, 2021: 100, 2022: 100}, "2021-06-30", "2023-06-30", rate_bp=0, ebitda_pct=0,
              extra_8k=[(acc, "2023-05-15", "A wildfire damaged the main plant and operations stopped.")])
    assert res.verdict == "주의"
    assert any("최근 90일 고위험 수시공시" in r for r in res.reasons)
    assert res.first_event.startswith("2023-05-15")
