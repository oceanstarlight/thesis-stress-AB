import pytest

from riskprobe import reverse
from riskprobe.ledger import Threshold

FLOOR = Threshold(2.0, "user")
CAP = Threshold(5.0, "user")


def test_ebitda_drop_to_coverage_matches_bisection():
    r = reverse.ebitda_drop_to_coverage(160.0, 40.0, FLOOR)
    assert r.status == "computed" and r.unit == "%"
    assert r.shock == pytest.approx(50.0)  # 160 x 0.5 / 40 = 2.0
    s = reverse.solve_monotone(lambda x: 160 * (1 - x) / 40, 2.0, 0.0, 1.0)
    assert r.shock == pytest.approx(s * 100)
    assert r.current == pytest.approx(4.0)
    assert r.grade == "여유 충분"


def test_rate_rise_to_coverage_in_basis_points():
    r = reverse.rate_rise_to_coverage(160.0, 40.0, 1000.0, FLOOR)
    assert r.shock == pytest.approx(400.0)  # (80 - 40) / 1000 = 4%
    r = reverse.rate_rise_to_coverage(85.0, 40.0, 1000.0, FLOOR)
    assert r.shock == pytest.approx(25.0) and r.grade == "근접"


def test_already_breached():
    r = reverse.ebitda_drop_to_coverage(60.0, 40.0, FLOOR)
    assert r.status == "breached" and r.shock < 0 and r.grade == "초과"


def test_leverage_path():
    r = reverse.ebitda_drop_to_leverage(500.0, 160.0, CAP)
    assert r.shock == pytest.approx((1 - 500 / 800) * 100)
    assert r.current == pytest.approx(500 / 160)
    nc = reverse.ebitda_drop_to_leverage(-10.0, 160.0, CAP)
    assert nc.status == "not_applicable"


def test_missing_input_is_not_filled_in():
    r = reverse.rate_rise_to_coverage(160.0, 40.0, None, FLOOR)
    assert r.status == "missing_input" and r.shock is None
    assert [u.code for u in r.unknowns] == ["reverse_input_missing"]
    r = reverse.ebitda_drop_to_coverage(160.0, 40.0, None)
    assert [u.code for u in r.unknowns] == ["reverse_threshold_missing"]
    assert not any(ch.isdigit() for u in r.unknowns for ch in u.message)


def test_required_growth():
    r = reverse.required_growth(100.0, 121.0, 2)
    assert r.shock == pytest.approx(10.0)
    assert reverse.required_growth(0.0, 121.0, 2).status == "not_applicable"


def test_default_threshold_is_labeled():
    th = reverse.default_threshold("interest_coverage")
    assert th.source == "default_rule" and "기본 규칙" in th.note
    assert reverse.default_threshold("unknown_indicator") is None


def test_result_is_labeled_conditional():
    assert "예측 아님" in reverse.ebitda_drop_to_coverage(160.0, 40.0, FLOOR).note


def test_solve_monotone_out_of_range():
    assert reverse.solve_monotone(lambda x: x, 5.0, 0.0, 1.0) is None


def test_non_positive_ebitda_counts_as_breached_with_reason():
    for r in (reverse.ebitda_drop_to_coverage(-10.0, 40.0, FLOOR), reverse.ebitda_drop_to_leverage(500.0, -10.0, CAP)):
        assert r.status == "breached" and r.grade == "초과"
        assert [u.code for u in r.unknowns] == ["reverse_negative_ebitda"]
