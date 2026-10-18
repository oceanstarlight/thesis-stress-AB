import json

from riskprobe import config, events, indicators, pit
from riskprobe.sources import dart, market, rates
from tests import fakes

KEY = "test-dart-key"
CORP = "00000001"
CORPS = [{"corp_code": CORP, "corp_name": "테스트항공", "corp_eng_name": "TEST AIR CO.,LTD", "stock_code": "123450"},
         {"corp_code": "00000002", "corp_name": "테스트항공우", "corp_eng_name": "", "stock_code": "123455"},
         {"corp_code": "00000003", "corp_name": "다른전자", "corp_eng_name": "OTHER ELECTRONICS", "stock_code": "999990"}]


def row(sj, aid, nm, cur, prev=None, add=None, prev_add=None, rcept="20241114000001"):
    return {"rcept_no": rcept, "sj_div": sj, "account_id": aid, "account_nm": nm, "thstrm_amount": cur,
            "frmtrm_amount": prev, "thstrm_add_amount": add, "frmtrm_add_amount": prev_add, "currency": "KRW"}


def listing(items):
    return {"status": "000", "total_page": 1, "list": [
        {"rcept_no": r, "report_nm": nm, "rcept_dt": r[:8]} for r, nm in items]}


def make_http(tmp_path, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", KEY)
    idx = tmp_path / "dart_corps.json"
    idx.write_text(json.dumps(CORPS, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "DART_INDEX", idx)
    http = fakes.FakeHttp()
    api = dart.API
    http.add(f"{api}/company.json", {"status": "000", "corp_name": "(주)테스트항공", "acc_mt": "12", "induty_code": "511"})
    http.add(f"{api}/list.json", listing([
        ("20240515000001", "분기보고서 (2024.03)"),
        ("20240814000001", "반기보고서 (2024.06)"),
        ("20241114000001", "분기보고서 (2024.09)"),
        ("20250318000001", "사업보고서 (2024.12)"),
        ("20250401000001", "[기재정정]사업보고서 (2024.12)"),
    ]), params={"pblntf_ty": "A"})
    http.add(f"{api}/list.json", listing([
        ("20250102000001", "주요사항보고서(회생절차개시신청)"),
        ("20250103000001", "[기재정정]주요사항보고서(회생절차개시신청)"),
        ("20250104000001", "주요사항보고서(유상증자결정)"),
    ]), params={"pblntf_ty": "B"})
    http.add(f"{api}/list.json", listing([
        ("20250105000001", "타인에대한채무보증결정"),  # info: dropped from exchange filings
        ("20250106000001", "소송등의제기ㆍ신청(일정금액이상의청구)"),
    ]), params={"pblntf_ty": "I"})
    no_data = {"status": "013", "message": "조회된 데이타가 없습니다."}
    for code in ("11013", "11012"):
        http.add(f"{api}/fnlttSinglAcntAll.json", no_data, params={"reprt_code": code})
    http.add(f"{api}/fnlttSinglAcntAll.json", {"status": "000", "list": [
        row("BS", "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "100"),
        row("BS", "-표준계정코드 미사용-", "단기차입금", "300"),
        row("BS", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued", "사채", "200"),
        row("BS", "ifrs-full_NoncurrentLeaseLiabilities", "리스부채", "500"),
        row("BS", "ifrs-full_NoncurrentFinanceLeaseReceivables", "리스채권", "999"),  # an asset, not debt
        row("CIS", "ifrs-full_Revenue", "매출액", "1000", add="3000", prev_add="2700"),
        row("CIS", "dart_OperatingIncomeLoss", "영업이익", "100", add="300", prev_add="200"),
        row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "400", prev="350"),
        row("CF", "dart_AdjustmentsForInterestExpenses", "이자비용", "60", prev="45"),
    ]}, params={"bsns_year": "2024", "reprt_code": "11014"})
    a = "20250401000001"  # the API answers with the amended version
    http.add(f"{api}/fnlttSinglAcntAll.json", {"status": "000", "list": [
        row("BS", "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "150", prev="90", rcept=a),
        row("BS", "-표준계정코드 미사용-", "단기차입금", "350", rcept=a),
        row("BS", "ifrs-full_NoncurrentLeaseLiabilities", "리스부채", "450", rcept=a),
        row("CIS", "ifrs-full_Revenue", "매출액", "4100", prev="3700", rcept=a),
        row("CIS", "dart_OperatingIncomeLoss", "영업이익", "420", prev="280", rcept=a),
        row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "520", prev="480", rcept=a),
        row("CF", "dart_AdjustmentsForInterestExpenses", "이자비용", "80", prev="62", rcept=a),
    ]}, params={"bsns_year": "2024", "reprt_code": "11011"})
    return http


def test_search_by_korean_english_and_code(tmp_path, monkeypatch):
    src = dart.DartSource(make_http(tmp_path, monkeypatch))
    assert [c.cik for c in src.search("테스트항공")][:2] == ["KR:123450", "KR:123455"]  # exact name first
    assert src.search("test air")[0].title == "테스트항공"
    assert src.search("999990")[0].label == "다른전자 (999990 · 한국 DART)"
    assert src.corp_for("KR:123450")["corp_code"] == CORP
    assert src.search("없는회사") == []


def test_market_routing():
    assert market.is_kr("KR:005930") and market.is_kr("삼성전자")
    assert not market.is_kr("AES") and not market.is_kr("1603145")
    assert market.floating_rate("KR:005930") == "cd91" and market.floating_rate("AES") == "sofr"


def test_load_builds_point_in_time_facts_and_events(tmp_path, monkeypatch):
    res = dart.DartSource(make_http(tmp_path, monkeypatch)).load("테스트항공", since="2024-01-01")
    assert res.name == "(주)테스트항공"
    codes = {u.code for u in res.unknowns}
    assert {"dart_report_missing", "dart_amended_dating", "dart_debt_definition"} <= codes
    assert not any(ch.isdigit() for u in res.unknowns for ch in u.message)

    q3 = [f for f in res.facts if f.document_id == "20241114000001"]
    debt = next(f for f in q3 if f.concept == "dart-calc:TotalBorrowings" and f.period_end == "2024-09-30")
    assert debt.value == 1000  # 300 (no standard id, matched by name) + 200 + 500, lease receivable excluded
    rev = {(f.period_start, f.period_end): f.value for f in q3 if f.concept == "ifrs-full:Revenue"}
    assert rev[("2024-07-01", "2024-09-30")] == 1000 and rev[("2024-01-01", "2024-09-30")] == 3000
    assert rev[("2023-01-01", "2023-09-30")] == 2700

    fy = [f for f in res.facts if f.concept == "ifrs-full:Revenue" and f.period_end == "2024-12-31"][0]
    assert fy.published_at == "2025-04-01" and fy.form == "사업보고서/A"  # dated at the amendment
    assert pit.snapshot(res.facts, "2025-03-31").get("ifrs-full:Revenue", "2024-01-01", "2024-12-31", "KRW") is None

    evs, _ = events.scan(None, res.filings, "2024-12-31", "2025-12-31")
    assert [(e.date, e.labels[0], e.severity, e.filing.items) for e in evs] == [
        ("2025-01-02", "파산·회생·부도", "high", "1.03"), ("2025-01-04", "증자·사채 발행", "info", ""),
        ("2025-01-06", "소송", "medium", "")]


def test_indicators_use_krw_and_ebit_when_depreciation_missing(tmp_path, monkeypatch):
    res = dart.DartSource(make_http(tmp_path, monkeypatch)).load("KR:123450", since="2024-01-01")
    book = indicators.Book(pit.snapshot(res.facts, "2025-06-30"))
    assert book.currency == "KRW" and book.anchor() == "2024-12-31"
    ind = indicators.compute(book)
    assert ind["ebitda"].value == 420 and ind["ebitda"].unit == "KRW"
    assert [u.code for u in ind["ebitda"].unknowns] == ["indicator_ebit_basis"]
    assert ind["interest_coverage"].value == 420 / 80 and "EBIT 기준" in ind["interest_coverage"].label_ko
    assert ind["net_debt_to_ebitda"].value == (800 - 150) / 420


def test_tag_title_rules():
    assert dart.tag_title("주요사항보고서(채권은행등의관리절차개시)")[0] == "1.03"
    assert dart.tag_title("기한의이익상실") [0] == "2.04"
    assert dart.tag_title("주요사항보고서(자기주식취득결정)") is None


def test_ecos_rates(monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    s, u = rates.fetch(fakes.FakeHttp(), "cd91", "2024-01-01", "2024-01-31")
    assert s is None and [x.code for x in u] == ["rates_no_key"]
    monkeypatch.setenv("ECOS_API_KEY", "ecos-key")
    http = fakes.FakeHttp()
    http.add(rates.ECOS.format(key="ecos-key", frm="20240101", to="20240131", item="010502000"),
             {"StatisticSearch": {"row": [{"TIME": "20240102", "DATA_VALUE": "3.83"}, {"TIME": "20240131", "DATA_VALUE": "3.68"}]}})
    s, u = rates.fetch(http, "cd91", "2024-01-01", "2024-01-31")
    assert u == [] and round(s.change_bp("2024-01-02", "2024-01-31")[0]) == -15 and "ecos-key" not in s.url
