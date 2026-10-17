from riskprobe import counter, events
from riskprobe.indicators import Indicator
from riskprobe.sources.sec import Filing


def ind(key, value, label="x"):
    return Indicator(key, label, "x", "", value=value)


def test_rules_fire_only_past_their_thresholds():
    now = {"ocf_to_net_income": ind("ocf_to_net_income", 0.5), "current_ratio": ind("current_ratio", 1.2),
           "interest_coverage": ind("interest_coverage", 2.0), "net_debt_to_ebitda": ind("net_debt_to_ebitda", 5.0),
           "dso": ind("dso", 70.0), "revenue_yoy": ind("revenue_yoy", 3.0)}
    prev = {"interest_coverage": ind("interest_coverage", 3.0), "net_debt_to_ebitda": ind("net_debt_to_ebitda", 4.9),
            "dso": ind("dso", 50.0)}
    alert = events.Event("2024-03-01", Filing("a", "8-K", "2024-03-01", "", "", "2.04", "https://x"), ["채무 조기상환 사유 발생"], "high")
    info = events.Event("2024-04-01", Filing("b", "8-K", "2024-04-01", "", "", "5.02", "https://y"), ["임원·이사 변동"], "info")
    found = counter.find(None, now, prev, [alert, info], None)
    labels = [c.label_ko for c in found]
    assert "이익의 현금 전환이 약함" in labels
    assert "이자보상배율이 1년 전보다 낮아짐" in labels  # -33%
    assert "차입 배수가 1년 전보다 높아짐" not in labels  # +2% only
    assert "매출채권 회수 기간이 길어짐" in labels
    assert "유동부채가 유동자산보다 많음" not in labels
    assert [c.source for c in found if c.source == "event"] == ["event"]
    assert all("기본 규칙" in c.detail for c in found if c.source in ("indicator", "trend"))


def test_negative_ocf_ratio_is_not_flagged_as_weak_conversion():
    # Negative net income makes the ratio meaningless; it is not reported as a counter-signal.
    assert counter.find(None, {"ocf_to_net_income": ind("ocf_to_net_income", -2.0)}, {}, [], None) == []
