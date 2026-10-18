"""Indicator catalog: fixed line items and ratios computed from a point-in-time snapshot.

Line items list alternative XBRL concepts in priority order. Companies switch tags over time
(e.g. ``InterestExpense`` -> ``InterestExpenseNonoperating`` from 2024), so the alternative is
chosen per period, and the concept actually used is kept with the value. Company-specific
extension tags are not in SEC companyfacts; a line item with no alternative reported stays
missing and becomes an ``Unknown`` instead of being filled in.

Flows (income and cash flow items) are turned into discrete quarters: directly reported
quarters first, otherwise differences of year-to-date values (cash flow statements in 10-Qs
are year-to-date only, and Q4 is only implied by the annual figure). Trailing twelve months
(TTM) is, in order: the fiscal-year figure ending on the date; last fiscal year + current
year-to-date - prior year-to-date; the sum of four quarters.

Values from both sides of a restatement (e.g. a 10-K that recasts the prior year after a
divestiture) are never combined: a derived quarter or TTM that would mix bases is not
computed, and the reason is kept in ``Book.unknowns``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from riskprobe.models import Fact, Unknown
from riskprobe.pit import Snapshot

# A company reports in one currency; SEC filers in USD, DART filers in KRW.
MONEY_UNITS = ("USD", "KRW")
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)


@dataclass(frozen=True)
class LineItem:
    id: str
    label_ko: str
    flow: bool  # True: income/cash flow over a period; False: balance at a date
    alternatives: tuple[tuple[str, ...], ...]  # each alternative is a sum of concepts
    nonnegative: bool = False  # a negative value is a sign-tagging error (seen: CCI 10-K interest)


def _alts(*names: str | tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    out = []
    for n in names:
        parts = (n,) if isinstance(n, str) else n
        out.append(tuple(c if ":" in c else f"us-gaap:{c}" for c in parts))
    return tuple(out)


LINE_ITEMS = {li.id: li for li in [
    LineItem("revenue", "매출", True, _alts("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "ifrs-full:Revenue")),
    LineItem("gross_profit", "매출총이익", True, _alts("GrossProfit", "ifrs-full:GrossProfit")),
    LineItem("operating_income", "영업이익", True, _alts("OperatingIncomeLoss", "dart:OperatingIncomeLoss")),
    LineItem("d_and_a", "감가상각비", True, _alts("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                                               "DepreciationAmortizationAndAccretionNet",
                                               "UtilitiesOperatingExpenseDepreciationAndAmortization", "Depreciation",
                                               "dart-calc:DepreciationAndAmortisation"), nonnegative=True),
    LineItem("pretax_income", "법인세차감전이익", True, _alts(
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ifrs-full:ProfitLossBeforeTax")),
    LineItem("interest_expense", "이자비용", True, _alts("InterestExpense", "InterestExpenseNonoperating",
                                                      "InterestExpenseDebt", "InterestAndDebtExpense",
                                                      # DART: cash flow add-back, then a face line, then cash interest paid
                                                      "dart:AdjustmentsForInterestExpenses", "ifrs-full:InterestExpense",
                                                      "dart-calc:InterestPaid"), nonnegative=True),
    LineItem("net_income", "순이익", True, _alts("NetIncomeLoss", "ProfitLoss", "ifrs-full:ProfitLoss")),
    LineItem("operating_cash_flow", "영업현금흐름", True, _alts("NetCashProvidedByUsedInOperatingActivities",
                                                           "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                                                           "ifrs-full:CashFlowsFromUsedInOperatingActivities")),
    LineItem("capex", "설비투자", True, _alts("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                                         "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"), nonnegative=True),
    LineItem("cash", "현금성자산", False, _alts("CashAndCashEquivalentsAtCarryingValue", "ifrs-full:CashAndCashEquivalents"), nonnegative=True),
    LineItem("total_debt", "총차입금", False, _alts(
        "LongTermDebt", "DebtAndCapitalLeaseObligations", "DebtLongtermAndShorttermCombinedAmount",
        ("LongTermDebtNoncurrent", "LongTermDebtCurrent"), ("LongTermDebtNoncurrent", "DebtCurrent"),
        ("LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        ("LongTermDebtAndCapitalLeaseObligations", "DebtCurrent"),
        "dart-calc:TotalBorrowings"), nonnegative=True),
    LineItem("short_term_borrowings", "단기차입금", False, _alts("ShortTermBorrowings", "CommercialPaper"), nonnegative=True),
    # Impairments, for adjusted EBITDA (PLANS.md 12). Goodwill and other assets are separate
    # groups because companies tag them separately; within a group the first tag found is used.
    LineItem("impairment_goodwill", "영업권 손상차손", True, _alts("GoodwillAndIntangibleAssetImpairment", "GoodwillImpairmentLoss",
                                                                     "dart:AdjustmentsForImpairmentLossesOfIntangibleAssets"),
             nonnegative=True),
    LineItem("impairment_assets", "자산 손상차손", True, _alts("AssetImpairmentCharges", "ImpairmentOfLongLivedAssetsHeldForUse",
                                                              "dart:AdjustmentsForImpairmentLossesOfPropertyPlantAndEquipment"),
             nonnegative=True),
    LineItem("current_assets", "유동자산", False, _alts("AssetsCurrent", "ifrs-full:CurrentAssets")),
    LineItem("current_liabilities", "유동부채", False, _alts("LiabilitiesCurrent", "ifrs-full:CurrentLiabilities")),
    LineItem("inventory", "재고자산", False, _alts("InventoryNet", "ifrs-full:Inventories"), nonnegative=True),
    LineItem("receivables", "매출채권", False, _alts("AccountsReceivableNetCurrent", "ifrs-full:TradeAndOtherCurrentReceivables",
                                                     "dart:ShortTermTradeReceivable"), nonnegative=True),
]}


@dataclass
class Measured:
    value: float
    period_start: str | None
    period_end: str
    facts: list[Fact]
    method: str  # reported | ytd_difference | fy | sum_of_quarters | instant

    @property
    def concepts(self) -> list[str]:
        return sorted({f.concept for f in self.facts})


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _shift_day(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def _quarters_of(snap: Snapshot, concept: str) -> dict[str, Measured]:
    durs = [f for f in snap.facts.values() if f.concept == concept and f.unit in MONEY_UNITS and f.days]
    out: dict[str, Measured] = {}
    for f in durs:
        if QUARTER_DAYS[0] <= f.days <= QUARTER_DAYS[1]:
            out[f.period_end] = Measured(f.value, f.period_start, f.period_end, [f], "reported")
    by_start: dict[str, list[Fact]] = {}
    for f in durs:
        by_start.setdefault(f.period_start, []).append(f)
    for fs in by_start.values():
        fs.sort(key=lambda f: f.days)
        for a, b in zip(fs, fs[1:]):
            if b.period_end not in out and QUARTER_DAYS[0] <= b.days - a.days <= QUARTER_DAYS[1] \
                    and not snap.mixes_bases([a, b]):
                out[b.period_end] = Measured(b.value - a.value, a.period_end, b.period_end, [a, b], "ytd_difference")
    return out


def _years_of(snap: Snapshot, concept: str) -> dict[str, Measured]:
    return {f.period_end: Measured(f.value, f.period_start, f.period_end, [f], "fy")
            for f in snap.facts.values()
            if f.concept == concept and f.unit in MONEY_UNITS and f.days and YEAR_DAYS[0] <= f.days <= YEAR_DAYS[1]}


def _instants_of(snap: Snapshot, concept: str) -> dict[str, Measured]:
    return {f.period_end: Measured(f.value, None, f.period_end, [f], "instant")
            for f in snap.facts.values() if f.concept == concept and f.unit in MONEY_UNITS and f.period_start is None}


def _merge(per_alt: list[dict[str, Measured]]) -> dict[str, Measured]:
    """Per period, the first alternative (priority order) that has a value."""
    out: dict[str, Measured] = {}
    for series in per_alt:
        for end, m in series.items():
            out.setdefault(end, m)
    return out


def _sum_alternative(snap: Snapshot, parts: tuple[str, ...], getter) -> dict[str, Measured]:
    series = [getter(snap, c) for c in parts]
    common = set(series[0]).intersection(*series[1:]) if len(series) > 1 else set(series[0])
    out = {}
    for end in common:
        ms = [s[end] for s in series]
        out[end] = Measured(sum(m.value for m in ms), ms[0].period_start, end, [f for m in ms for f in m.facts], ms[0].method)
    return out


class Book:
    """Line item series of one snapshot, computed lazily."""

    def __init__(self, snap: Snapshot):
        self.snap = snap
        units = [f.unit for f in snap.facts.values() if f.unit in MONEY_UNITS]
        self.currency = max(set(units), key=units.count) if units else "USD"
        self._cache: dict[tuple, dict[str, Measured]] = {}
        self.unknowns: list[Unknown] = []

    def _series(self, item_id: str, getter) -> dict[str, Measured]:
        key = (item_id, getter.__name__)
        if key not in self._cache:
            li = LINE_ITEMS[item_id]
            per_alt = [_sum_alternative(self.snap, alt, getter) for alt in li.alternatives]
            if li.nonnegative:
                per_alt = [{e: m for e, m in series.items() if self._sign_ok(li, m)} for series in per_alt]
            self._cache[key] = _merge(per_alt)
        return self._cache[key]

    def _sign_ok(self, li: LineItem, m: Measured) -> bool:
        if m.value >= 0 and all(f.value >= 0 for f in m.facts):
            return True
        code = "sign_error_suspected"
        if not any(u.code == code and u.detail.startswith(li.id) for u in self.unknowns):
            self.unknowns.append(Unknown(code, f"{li.label_ko}: 음수일 수 없는 값이 음수로 보고돼 부호 오류로 보고 제외함",
                                         f"{li.id}: {[(f.document_id, f.period_end, f.value) for f in m.facts if f.value < 0]}"))
        return False

    def quarters(self, item_id: str) -> dict[str, Measured]:
        return self._series(item_id, _quarters_of)

    def years(self, item_id: str) -> dict[str, Measured]:
        return self._series(item_id, _years_of)

    def instants(self, item_id: str) -> dict[str, Measured]:
        return self._series(item_id, _instants_of)

    def ttm(self, item_id: str, end: str) -> Measured | None:
        fy = self.years(item_id).get(end)
        if fy is not None:
            return fy
        ltm = self._ltm(item_id, end)
        if ltm is not None:
            return ltm
        q = self.quarters(item_id)
        ends = sorted(e for e in q if e <= end)[-4:]
        if len(ends) < 4 or ends[-1] != end or _days_between(ends[0], end) > 290:
            return None
        if any(not QUARTER_DAYS[0] <= _days_between(a, b) <= QUARTER_DAYS[1] for a, b in zip(ends, ends[1:])):
            return None
        ms = [q[e] for e in ends]
        facts = [f for m in ms for f in m.facts]
        if self.snap.mixes_bases(facts):
            self.unknowns.append(Unknown("ttm_mixed_bases", f"{LINE_ITEMS[item_id].label_ko}: 재작성 공시로 기준이 바뀐 분기 값이 섞여 최근 열두 달 값을 계산하지 않음",
                                         f"{item_id} @ {end}"))
            return None
        return Measured(sum(m.value for m in ms), ms[0].period_start, end, facts, "sum_of_quarters")

    def _ltm(self, item_id: str, end: str) -> Measured | None:
        """Last fiscal year + current year-to-date - prior year-to-date, one concept at a time."""
        for alt in LINE_ITEMS[item_id].alternatives:
            if len(alt) != 1:
                continue
            durs = [f for f in self.snap.facts.values() if f.concept == alt[0] and f.unit in MONEY_UNITS and f.days]
            years = [f for f in durs if YEAR_DAYS[0] <= f.days <= YEAR_DAYS[1] and f.period_end < end]
            if not years:
                continue
            fy = max(years, key=lambda f: f.period_end)
            cur = [f for f in durs if f.period_end == end and abs(_days_between(_shift_day(fy.period_end, 1), f.period_start)) <= 7]
            prev_end = _one_year_before(end)
            prior = [f for f in durs if abs(_days_between(f.period_end, prev_end)) <= 7
                     and abs(_days_between(fy.period_start, f.period_start)) <= 7]
            if not cur or not prior or _days_between(fy.period_end, end) > 300:
                continue
            used = [fy, cur[0], prior[0]]
            if self.snap.mixes_bases(used):
                continue
            if LINE_ITEMS[item_id].nonnegative and not self._sign_ok(LINE_ITEMS[item_id], Measured(0.0, None, end, used, "ltm")):
                continue
            return Measured(fy.value + cur[0].value - prior[0].value, _shift_day(_one_year_before(end), 1), end, used, "ltm")
        return None

    def ttm_sparse(self, item_id: str, end: str) -> tuple[Measured | None, list[str]]:
        """TTM for items reported only when non-zero (impairments).

        Last fiscal year + current year-to-date - prior year-to-date, where a part that was not
        reported counts as zero. Returns (value, parts assumed zero); None when nothing was
        reported in the window. The assumption is shown with the result."""
        fy_ends = sorted(e for item in ("revenue", "operating_cash_flow") for e in self.years(item) if e <= end)
        if not fy_ends or _days_between(fy_ends[-1], end) > 300:
            return None, []
        fy_end = fy_ends[-1]
        li = LINE_ITEMS[item_id]
        for alt in li.alternatives:
            durs = [f for f in self.snap.facts.values() if f.concept == alt[0] and f.unit in MONEY_UNITS and f.days]
            fy = next((f for f in durs if f.period_end == fy_end and YEAR_DAYS[0] <= f.days <= YEAR_DAYS[1]), None)
            if fy_end == end:
                cur = prior = None
            else:
                cur = next((f for f in durs if f.period_end == end
                            and abs(_days_between(_shift_day(fy_end, 1), f.period_start)) <= 7), None)
                prev_end, fy_start = _one_year_before(end), _shift_day(_one_year_before(fy_end), 1)
                prior = next((f for f in durs if abs(_days_between(f.period_end, prev_end)) <= 7
                              and abs(_days_between(f.period_start, fy_start)) <= 7), None)
            parts = {"직전 연간": fy, "당기 누계": cur, "전기 누계": prior}
            used = [f for f in parts.values() if f is not None]
            if not used:
                continue
            m = Measured((fy.value if fy else 0.0) + (cur.value if cur else 0.0) - (prior.value if prior else 0.0),
                         None, end, used, "ltm_sparse")
            if self.snap.mixes_bases(used) or not self._sign_ok(li, Measured(0.0, None, end, used, "ltm_sparse")):
                return None, []
            zero = [k for k, f in parts.items() if f is None and not (fy_end == end and k != "직전 연간")]
            return m, zero
        return None, []

    def at(self, item_id: str, end: str) -> Measured | None:
        """Balance at ``end`` (within a few days, fiscal calendars drift)."""
        for e, m in self.instants(item_id).items():
            if abs(_days_between(e, end)) <= 7:
                return m
        return None

    def anchor(self) -> str | None:
        """Latest quarter end with revenue or operating cash flow: the date indicators describe."""
        ends = [e for item in ("revenue", "operating_cash_flow") for e in self.quarters(item)]
        ends += [e for item in ("revenue", "operating_cash_flow") for e in self.years(item)]
        return max(ends) if ends else None


@dataclass
class Indicator:
    id: str
    label_ko: str
    unit: str  # x | % | days | USD
    formula: str
    value: float | None = None
    period_end: str = ""
    inputs: dict[str, Measured] = field(default_factory=dict)
    unknowns: list[Unknown] = field(default_factory=list)


def _one_year_before(end: str) -> str:
    d = date.fromisoformat(end)
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28).isoformat()


def _find_near(series: dict[str, Measured], end: str) -> Measured | None:
    for e, m in series.items():
        if abs(_days_between(e, end)) <= 7:
            return m
    return None


def _need(ind: Indicator, **inputs: Measured | None) -> bool:
    missing = [k for k, v in inputs.items() if v is None]
    for k in missing:
        ind.unknowns.append(Unknown("indicator_input_missing", f"{ind.label_ko} 계산에 필요한 {LINE_ITEMS[k.split('__')[0]].label_ko} 값이 없어 계산하지 않음",
                                    f"{k} @ {ind.period_end}"))
    ind.inputs.update({k: v for k, v in inputs.items() if v is not None})
    return not missing


def _ratio(ind: Indicator, num: float, den: float, scale: float = 1.0) -> Indicator:
    if den == 0:
        ind.unknowns.append(Unknown("indicator_zero_denominator", f"{ind.label_ko}의 분모가 영이라 계산하지 않음"))
    else:
        ind.value = num / den * scale
    return ind


def compute(book: Book, end: str | None = None) -> dict[str, Indicator]:
    """All catalog indicators at ``end`` (default: the snapshot's anchor date)."""
    end = end or book.anchor()
    out: dict[str, Indicator] = {}
    if end is None:
        return out
    prev = _one_year_before(end)

    def new(id_, label, unit, formula):
        ind = Indicator(id_, label, unit, formula, period_end=end)
        out[id_] = ind
        return ind

    rev_q, rev_q_prev = book.quarters("revenue").get(end), _find_near(book.quarters("revenue"), prev)
    ind = new("revenue_yoy", "분기 매출 전년 대비 증가율", "%", "분기 매출 / 전년 같은 분기 매출 - 1")
    if _need(ind, revenue=rev_q, revenue__prev=rev_q_prev):
        _ratio(ind, rev_q.value - rev_q_prev.value, rev_q_prev.value, 100)

    rev, gp, oi = book.ttm("revenue", end), book.ttm("gross_profit", end), book.ttm("operating_income", end)
    ind = new("gross_margin", "매출총이익률(TTM)", "%", "매출총이익 / 매출")
    if _need(ind, gross_profit=gp, revenue=rev):
        _ratio(ind, gp.value, rev.value, 100)
    ind = new("operating_margin", "영업이익률(TTM)", "%", "영업이익 / 매출")
    if _need(ind, operating_income=oi, revenue=rev):
        _ratio(ind, oi.value, rev.value, 100)

    da, interest = book.ttm("d_and_a", end), book.ttm("interest_expense", end)
    ind = new("ebitda", "EBITDA(TTM)", book.currency, "영업이익 + 감가상각비")
    pretax = book.ttm("pretax_income", end)
    if oi is None and pretax is not None and interest is not None and da is not None:
        # No operating income tag (e.g. AES): EBIT approximated as pretax income + interest.
        ind.formula = "법인세차감전이익 + 이자비용 + 감가상각비 (영업이익 태그 없음, 영업외 손익 포함)"
        ind.inputs.update(pretax_income=pretax, interest_expense=interest, d_and_a=da)
        ind.value = pretax.value + interest.value + da.value
        oi = Measured(pretax.value + interest.value, pretax.period_start, end, pretax.facts + interest.facts, "derived")
    elif oi is not None and da is None and book.currency == "KRW":
        # Decided with the user: Korean face statements often omit depreciation; use operating
        # income (EBIT) instead and say so. EBIT <= EBITDA, so every ratio is stricter.
        ind.label_ko = "EBIT(TTM, 감가상각비 미공시로 EBITDA 대신 영업이익)"
        ind.formula = "영업이익 (감가상각비가 재무제표 본문에 없어 더하지 않음, 실제보다 엄격)"
        ind.inputs.update(operating_income=oi)
        ind.value = oi.value
        ind.unknowns.append(Unknown("indicator_ebit_basis", "감가상각비가 재무제표 본문에 없어 EBITDA 대신 영업이익을 씀. 실제보다 엄격하게 계산됨"))
        da = Measured(0.0, oi.period_start, end, [], "not_reported")
    elif _need(ind, operating_income=oi, d_and_a=da):
        ind.value = oi.value + da.value
    ebitda = out["ebitda"].value
    basis = "EBIT" if da is not None and da.method == "not_reported" else "EBITDA"

    ind = new("interest_coverage", f"이자보상배율(TTM, {basis} 기준)", "x", f"{basis} / 이자비용")
    if ebitda is not None and _need(ind, operating_income=oi, d_and_a=da, interest_expense=interest):
        _ratio(ind, ebitda, interest.value)
    elif ebitda is None:
        _need(ind, operating_income=oi, d_and_a=da)

    debt, cash = book.at("total_debt", end), book.at("cash", end)
    ind = new("net_debt_to_ebitda", f"순차입금/{basis}", "x", f"(총차입금 - 현금성자산) / {basis}")
    if ebitda is not None and _need(ind, total_debt=debt, cash=cash, operating_income=oi, d_and_a=da):
        if ebitda <= 0:
            ind.unknowns.append(Unknown("indicator_negative_ebitda", "EBITDA가 영 이하라 차입 배수가 의미 없어 계산하지 않음"))
        else:
            _ratio(ind, debt.value - cash.value, ebitda)
    elif ebitda is None:
        _need(ind, total_debt=debt, cash=cash, operating_income=oi, d_and_a=da)

    # Adjusted EBITDA: add back impairments found in standard tags (PLANS.md 12, option B).
    imp_parts = {k: book.ttm_sparse(k, end) for k in ("impairment_goodwill", "impairment_assets")}
    found = {k: v for k, v in imp_parts.items() if v[0] is not None}
    ind = new("ebitda_adjusted", "조정 EBITDA(TTM, 손상차손 가산)", book.currency,
              "EBITDA + 표준 태그로 확인된 손상차손 (영업권 + 기타 자산)")
    if ebitda is not None and found:
        ind.inputs.update({k: v[0] for k, v in found.items()})
        ind.value = ebitda + sum(v[0].value for v in found.values())
        zero = sorted({z for v in found.values() for z in v[1]})
        if zero:
            ind.formula += " · 보고되지 않은 기간(" + ", ".join(zero) + ")은 손상차손 없음으로 간주"
        if len(found) < len(imp_parts):
            ind.unknowns.append(Unknown("impairment_partial", "일부 손상차손 항목은 표준 태그로 확인되지 않아 더하지 않음"))
    elif ebitda is not None:
        ind.unknowns.append(Unknown("impairment_not_found", "최근 열두 달 손상차손이 표준 태그로 확인되지 않아 조정하지 않음"))
    adj = out["ebitda_adjusted"].value
    if adj is not None:
        ind = new("interest_coverage_adjusted", "이자보상배율(조정 EBITDA 기준)", "x", "조정 EBITDA / 이자비용")
        if _need(ind, interest_expense=interest):
            _ratio(ind, adj, interest.value)
        ind = new("net_debt_to_ebitda_adjusted", "순차입금/조정 EBITDA", "x", "(총차입금 - 현금성자산) / 조정 EBITDA")
        if _need(ind, total_debt=debt, cash=cash):
            if adj <= 0:
                ind.unknowns.append(Unknown("indicator_negative_ebitda", "조정 EBITDA가 영 이하라 차입 배수가 의미 없어 계산하지 않음"))
            else:
                _ratio(ind, debt.value - cash.value, adj)

    std = book.at("short_term_borrowings", end)
    ind = new("short_term_debt_share", "단기차입 비중", "%", "단기차입금 / (총차입금 + 단기차입금)")
    if _need(ind, short_term_borrowings=std, total_debt=debt):
        _ratio(ind, std.value, debt.value + std.value, 100)

    ocf, ni = book.ttm("operating_cash_flow", end), book.ttm("net_income", end)
    ind = new("ocf_to_net_income", "영업현금흐름/순이익(TTM)", "x", "영업현금흐름 / 순이익")
    if _need(ind, operating_cash_flow=ocf, net_income=ni):
        _ratio(ind, ocf.value, ni.value)

    capex = book.ttm("capex", end)
    ind = new("capex_to_revenue", "설비투자/매출(TTM)", "%", "설비투자 / 매출")
    if _need(ind, capex=capex, revenue=rev):
        _ratio(ind, capex.value, rev.value, 100)

    inv, inv_prev, rev_prev = book.at("inventory", end), book.at("inventory", prev), book.ttm("revenue", prev)
    ind = new("inventory_minus_revenue_growth", "재고 증가율 - 매출 증가율", "%p", "재고 전년 대비 증가율 - 매출(TTM) 전년 대비 증가율")
    if _need(ind, inventory=inv, inventory__prev=inv_prev, revenue=rev, revenue__prev=rev_prev):
        if inv_prev.value and rev_prev.value:
            ind.value = ((inv.value / inv_prev.value) - (rev.value / rev_prev.value)) * 100
        else:
            ind.unknowns.append(Unknown("indicator_zero_denominator", f"{ind.label_ko}의 분모가 영이라 계산하지 않음"))

    ar = book.at("receivables", end)
    ind = new("dso", "매출채권 회전일수", "days", "매출채권 / 매출(TTM) × 365")
    if _need(ind, receivables=ar, revenue=rev):
        _ratio(ind, ar.value, rev.value, 365)

    ca, cl = book.at("current_assets", end), book.at("current_liabilities", end)
    ind = new("current_ratio", "유동비율", "x", "유동자산 / 유동부채")
    if _need(ind, current_assets=ca, current_liabilities=cl):
        _ratio(ind, ca.value, cl.value)
    return out
