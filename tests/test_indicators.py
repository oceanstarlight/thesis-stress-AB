import pytest

from riskprobe import indicators, pit
from riskprobe.models import Fact

F = "2025-05-01"  # one filing date for everything; point-in-time is tested in test_pit


def dur(concept, start, end, val, doc="D-1"):
    return Fact(f"us-gaap:{concept}", "USD", start, end, float(val), F, doc, "10-Q")


def inst(concept, end, val):
    return Fact(f"us-gaap:{concept}", "USD", None, end, float(val), F, "D-1", "10-Q")


Q = [("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30"), ("2024-07-01", "2024-09-30"),
     ("2024-10-01", "2024-12-31"), ("2025-01-01", "2025-03-31")]
FACTS = [
    # Revenue: quarters + year-to-date, Q4 only implied by FY - 9M.
    dur("Revenues", *Q[0], 100), dur("Revenues", *Q[1], 110), dur("Revenues", *Q[2], 120),
    dur("Revenues", "2024-01-01", "2024-06-30", 210), dur("Revenues", "2024-01-01", "2024-09-30", 330),
    dur("Revenues", "2024-01-01", "2024-12-31", 450), dur("Revenues", *Q[4], 115),
    # Operating cash flow: year-to-date only, as in 10-Q cash flow statements.
    dur("NetCashProvidedByUsedInOperatingActivities", "2024-01-01", "2024-03-31", 50),
    dur("NetCashProvidedByUsedInOperatingActivities", "2024-01-01", "2024-06-30", 110),
    dur("NetCashProvidedByUsedInOperatingActivities", "2024-01-01", "2024-09-30", 170),
    dur("NetCashProvidedByUsedInOperatingActivities", "2024-01-01", "2024-12-31", 240),
    dur("NetCashProvidedByUsedInOperatingActivities", *Q[4], 60),
    # Interest: tag switch in 2025.
    dur("InterestExpense", *Q[1], 10), dur("InterestExpense", *Q[2], 10), dur("InterestExpense", *Q[3], 10),
    dur("InterestExpenseNonoperating", *Q[4], 12),
    dur("NetIncomeLoss", *Q[1], 20), dur("NetIncomeLoss", *Q[2], 20), dur("NetIncomeLoss", *Q[3], 20),
    dur("NetIncomeLoss", *Q[4], 20),
    *[dur("OperatingIncomeLoss", *q, 30) for q in Q[1:]],
    *[dur("DepreciationAndAmortization", *q, 10) for q in Q[1:]],
    inst("LongTermDebtNoncurrent", "2025-03-31", 500), inst("LongTermDebtCurrent", "2025-03-31", 50),
    inst("CashAndCashEquivalentsAtCarryingValue", "2025-03-31", 50),
]


@pytest.fixture
def book():
    return indicators.Book(pit.snapshot(FACTS, "2025-06-30"))


def test_q4_is_derived_from_annual_minus_nine_months(book):
    q4 = book.quarters("revenue")["2024-12-31"]
    assert q4.value == 120 and q4.method == "ytd_difference"


def test_ytd_only_cash_flow_becomes_quarters(book):
    assert [book.quarters("operating_cash_flow")[e].value for e in sorted(book.quarters("operating_cash_flow"))] == [50, 60, 60, 70, 60]


def test_ttm_sums_four_consecutive_quarters(book):
    assert book.ttm("revenue", "2025-03-31").value == 110 + 120 + 120 + 115
    assert book.ttm("revenue", "2024-12-31").method == "fy"
    assert book.ttm("revenue", "2024-06-30") is None  # fewer than four quarters known


def test_tag_switch_is_bridged_per_period(book):
    m = book.ttm("interest_expense", "2025-03-31")
    assert m.value == 42
    assert m.concepts == ["us-gaap:InterestExpense", "us-gaap:InterestExpenseNonoperating"]


def test_debt_alternative_sums_parts(book):
    debt = book.at("total_debt", "2025-03-31")
    assert debt.value == 550 and len(debt.facts) == 2


def test_indicators(book):
    ind = indicators.compute(book)
    assert book.anchor() == "2025-03-31"
    assert ind["revenue_yoy"].value == pytest.approx(15.0)
    assert ind["ebitda"].value == 160
    assert ind["interest_coverage"].value == pytest.approx(160 / 42)
    assert ind["net_debt_to_ebitda"].value == pytest.approx(500 / 160)
    assert ind["ocf_to_net_income"].value == pytest.approx(250 / 80)
    assert ind["operating_margin"].value == pytest.approx(120 / 465 * 100)


def test_missing_inputs_are_unknowns_not_guesses(book):
    ind = indicators.compute(book)
    assert ind["gross_margin"].value is None
    assert ind["current_ratio"].value is None
    codes = {u.code for u in ind["gross_margin"].unknowns}
    assert codes == {"indicator_input_missing"}
    for i in ind.values():
        for u in i.unknowns:
            assert not any(ch.isdigit() for ch in u.message)


def test_indicator_keeps_input_evidence(book):
    cov = indicators.compute(book)["interest_coverage"]
    assert set(cov.inputs) == {"operating_income", "d_and_a", "interest_expense"}
    assert all(f.published_at <= "2025-06-30" for m in cov.inputs.values() for f in m.facts)


def test_empty_snapshot_has_no_indicators():
    assert indicators.compute(indicators.Book(pit.snapshot(FACTS, "2020-01-01"))) == {}


def test_ebitda_falls_back_to_pretax_plus_interest_when_no_operating_income():
    facts = [f for f in FACTS if f.concept != "us-gaap:OperatingIncomeLoss"]
    facts += [dur("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", *q, 20)
              for q in Q[1:]]
    ind = indicators.compute(indicators.Book(pit.snapshot(facts, "2025-06-30")))
    assert ind["ebitda"].value == 80 + 42 + 40
    assert "영업외" in ind["ebitda"].formula
    assert ind["interest_coverage"].value == pytest.approx(162 / 42)
    assert ind["operating_margin"].value is None


def test_restated_annual_is_not_combined_with_old_basis_quarters():
    """CCI 2025 case: the 10-K recasts the year (divestiture), the 9M figure is still the old basis."""
    old = [dur("InterestExpense", "2024-01-01", "2024-09-30", 700, doc="Q3"),
           dur("InterestExpense", "2023-01-01", "2023-12-31", 900, doc="FY23")]
    old = [Fact(f.concept, f.unit, f.period_start, f.period_end, f.value, "2024-10-30" if f.document_id == "Q3" else "2024-02-20",
                f.document_id, "10-Q" if f.document_id == "Q3" else "10-K") for f in old]
    recast = [Fact("us-gaap:InterestExpense", "USD", "2024-01-01", "2024-12-31", 600.0, "2025-03-14", "FY24", "10-K"),
              Fact("us-gaap:InterestExpense", "USD", "2023-01-01", "2023-12-31", 500.0, "2025-03-14", "FY24", "10-K")]
    b = indicators.Book(pit.snapshot(old + recast, "2025-04-01"))
    assert "2024-12-31" not in b.quarters("interest_expense")  # 600 - 700 would be nonsense
    assert b.ttm("interest_expense", "2024-12-31").value == 600  # the annual figure itself is fine


def test_ltm_formula_uses_one_basis():
    facts = [
        Fact("us-gaap:Revenues", "USD", "2024-01-01", "2024-12-31", 400.0, "2025-03-14", "FY24", "10-K"),
        Fact("us-gaap:Revenues", "USD", "2025-01-01", "2025-03-31", 110.0, "2025-05-09", "Q1", "10-Q"),
        Fact("us-gaap:Revenues", "USD", "2024-01-01", "2024-03-31", 100.0, "2025-05-09", "Q1", "10-Q"),
        Fact("us-gaap:Revenues", "USD", "2024-01-01", "2024-03-31", 130.0, "2024-05-01", "Q1-24", "10-Q"),  # old basis
    ]
    m = indicators.Book(pit.snapshot(facts, "2025-06-30")).ttm("revenue", "2025-03-31")
    assert m.method == "ltm" and m.value == 410


def test_negative_expense_is_treated_as_sign_error_not_flipped():
    facts = FACTS + [Fact("us-gaap:InterestExpense", "USD", "2024-01-01", "2024-12-31", -40.0, "2025-02-20", "FY", "10-K")]
    b = indicators.Book(pit.snapshot(facts, "2025-06-30"))
    assert "2024-12-31" not in b.years("interest_expense")
    assert [u.code for u in b.unknowns] == ["sign_error_suspected"]
    assert b.ttm("interest_expense", "2025-03-31").value == 42  # still from the reported quarters
