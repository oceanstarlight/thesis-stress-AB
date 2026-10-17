import pytest

from riskprobe.ledger import Assumption, Ledger, StatusEntry, Threshold


def make():
    lg = Ledger("AES", "AES Corp")
    lg.add(Assumption("A1", "이자보상배율이 기준 이상으로 유지된다", "financial", "interest_coverage", "above",
                      Threshold(2.0, "default_rule", "기본 규칙: interest_coverage"),
                      path_template="ebitda_drop_to_coverage", recorded_at="2023-06-30"))
    return lg


def test_roundtrip(tmp_path):
    lg = make()
    lg.record("A1", StatusEntry("2023-08-03", "supported", "기준 이상", ["https://www.sec.gov/x"]))
    back = Ledger.load(lg.save(tmp_path / "l.json"))
    assert back == lg
    assert back.assumptions[0].threshold.source == "default_rule"


def test_holds():
    a = make().assumptions[0]
    assert a.holds(2.5) is True and a.holds(1.5) is False
    a.threshold = None
    assert a.holds(2.5) is None


def test_validation():
    with pytest.raises(ValueError):
        Threshold(1.0, "llm_guess")
    with pytest.raises(ValueError):
        StatusEntry("2024-01-01", "probably_fine", "")
    lg = make()
    with pytest.raises(ValueError):
        lg.add(lg.assumptions[0])
