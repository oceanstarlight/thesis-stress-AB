from riskprobe import pit
from riskprobe.models import Fact

Q1 = ("2024-01-01", "2024-03-31")


def f(val, published, doc, period=Q1, concept="us-gaap:Revenues"):
    return Fact(concept, "USD", period[0], period[1], val, published, doc, "10-Q")


ORIGINAL = f(100.0, "2024-05-01", "A-1")
REPEAT = f(100.0, "2025-05-01", "A-2")  # same value reported again as a comparative
RESTATED = f(90.0, "2025-08-01", "A-3")
NEXT_Q = f(120.0, "2024-08-01", "A-4", period=("2024-04-01", "2024-06-30"))
FACTS = [RESTATED, NEXT_Q, REPEAT, ORIGINAL]


def test_nothing_published_after_as_of_is_visible():
    for as_of in ("2024-04-30", "2024-05-01", "2024-07-31", "2025-07-31", "2026-01-01"):
        snap = pit.snapshot(FACTS, as_of)
        assert pit.leaks(snap) == []
        assert all(x.published_at <= as_of for x in snap.facts.values())


def test_before_first_filing_the_value_is_unknown():
    assert pit.snapshot(FACTS, "2024-04-30").get("us-gaap:Revenues", *Q1) is None


def test_filing_date_itself_is_included():
    assert pit.snapshot(FACTS, "2024-05-01").get("us-gaap:Revenues", *Q1).value == 100.0


def test_restatement_applies_only_from_its_filing_date():
    assert pit.snapshot(FACTS, "2025-07-31").get("us-gaap:Revenues", *Q1).value == 100.0
    assert pit.snapshot(FACTS, "2025-08-01").get("us-gaap:Revenues", *Q1).value == 90.0


def test_restatement_keeps_original_as_separate_version():
    key = ORIGINAL.key
    assert [x.document_id for x in pit.versions(FACTS, key)] == ["A-1", "A-2", "A-3"]
    assert [(a.value, b.value) for a, b in pit.restatements(FACTS, key)] == [(100.0, 90.0)]


def test_same_day_conflict_is_reported():
    a, b = f(100.0, "2024-05-01", "B-1"), f(101.0, "2024-05-01", "B-2")
    snap = pit.snapshot([a, b], "2024-06-01")
    assert snap.get("us-gaap:Revenues", *Q1).document_id == "B-2"
    assert [u.code for u in snap.unknowns] == ["pit_same_day_conflict"]
    assert not any(ch.isdigit() for u in snap.unknowns for ch in u.message)


def test_replay_feed_is_ordered_and_bounded():
    feed = pit.published_between(FACTS, "2024-05-01", "2025-05-01")
    assert [x.document_id for x in feed] == ["A-4", "A-2"]


def test_series_filters_quarters():
    annual = f(400.0, "2025-02-01", "A-5", period=("2024-01-01", "2024-12-31"))
    snap = pit.snapshot(FACTS + [annual], "2025-03-01")
    assert [x.value for x in snap.series("us-gaap:Revenues", days=(80, 100))] == [100.0, 120.0]
    assert [x.value for x in snap.series("us-gaap:Revenues", days=(350, 380))] == [400.0]


def test_instant_values_have_no_duration():
    debt = Fact("us-gaap:LongTermDebt", "USD", None, "2024-03-31", 5.0, "2024-05-01", "A-1", "10-Q")
    assert debt.days is None
    assert pit.snapshot([debt], "2024-05-01").get("us-gaap:LongTermDebt", None, "2024-03-31").value == 5.0
