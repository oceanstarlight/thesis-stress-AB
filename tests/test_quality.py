from riskprobe import pit, quality
from riskprobe.models import Fact

KEY_PERIOD = ("2024-07-01", "2024-09-30")


def ie(val, filed, doc, form="10-Q", period=KEY_PERIOD):
    return Fact("us-gaap:InterestExpense", "USD", period[0], period[1], val, filed, doc, form)


# AES case (P0 findings): the Q1 2025 10-Q states a Q3 2024 value that differs from the reports around it.
Q3_2024 = ie(379.0, "2024-10-31", "Q3-24")
FY_2024 = ie(379.0, "2025-03-11", "FY-24", form="10-K")
Q1_2025 = ie(357.0, "2025-05-01", "Q1-25")
REPORT_DATES = {"Q3-24": "2024-09-30", "FY-24": "2024-12-31", "Q1-25": "2025-03-31"}


def test_out_of_period_detection():
    assert quality.out_of_period(Q1_2025, "2025-03-31")
    assert not quality.out_of_period(Q3_2024, "2024-09-30")
    assert not quality.out_of_period(FY_2024, "2024-12-31")


def test_out_of_period_repeat_of_earlier_value_is_kept():
    repeat = ie(379.0, "2025-05-01", "Q1-25b")
    excluded, _ = quality.screen([Q3_2024, repeat], {"Q3-24": "2024-09-30", "Q1-25b": "2025-03-31"})
    assert excluded == set()


def test_prior_year_comparative_is_not_suspect():
    comparative = ie(300.0, "2025-11-04", "Q3-25")
    assert not quality.out_of_period(comparative, "2025-09-30")


def test_balance_sheet_prior_year_end_is_not_suspect():
    bs = Fact("us-gaap:AssetsCurrent", "USD", None, "2024-12-31", 1.0, "2025-05-01", "Q1-25", "10-Q")
    assert not quality.out_of_period(bs, "2025-03-31")


def test_screened_snapshot_keeps_the_earlier_value():
    facts = [Q3_2024, FY_2024, Q1_2025]
    excluded, unknowns = quality.screen(facts, REPORT_DATES)
    assert excluded == {("Q1-25", Q1_2025.key)}
    assert [u.code for u in unknowns] == ["suspect_values_excluded"]
    assert pit.snapshot(facts, "2025-06-30").get("us-gaap:InterestExpense", *KEY_PERIOD).value == 357.0
    assert pit.snapshot(facts, "2025-06-30", exclude=excluded).get("us-gaap:InterestExpense", *KEY_PERIOD).value == 379.0


def test_recast_8k_is_kept_but_marked():
    recast = ie(370.0, "2025-06-01", "8K", form="8-K")
    assert not quality.out_of_period(recast, "")
    assert quality.is_recast(recast)


def test_cover_page_and_subsequent_event_dates_are_not_suspect():
    shares = Fact("dei:EntityCommonStockSharesOutstanding", "shares", None, "2025-04-28", 1.0, "2025-05-01", "Q1-25", "10-Q")
    assert not quality.out_of_period(shares, "2025-03-31")
    later = Fact("us-gaap:LongTermDebt", "USD", None, "2025-04-15", 1.0, "2025-05-01", "Q1-25", "10-Q")
    assert not quality.out_of_period(later, "2025-03-31")
