from riskprobe import audit, guidance
from riskprobe.guidance import Target, Targets
from riskprobe.ledger import Ledger
from riskprobe.sources import sec
from tests import fakes

CIK = "0000000042"
UA = "riskprobe test test@example.com"
ARCH = "https://www.sec.gov/Archives/edgar/data/42/{acc}/"
RELEASES = [  # (accession, filed, items, outlook sentence)
    ("0000000042-23-000010", "2023-04-25", "2.02,9.01", "We continue to see 12% to 15% growth per year in distributions per unit through at least 2026."),
    ("0000000042-23-000020", "2023-07-25", "2.02,9.01", "We continue to see 12% to 15% growth per year in distributions per unit through at least 2026."),
    ("0000000042-23-000030", "2023-10-24", "2.02,9.01", "We now see 5% to 8% growth per year in distributions per unit through at least 2026."),
    ("0000000042-24-000040", "2024-01-25", "2.02,9.01", "Fourth quarter results were reported today for the company and its subsidiaries."),
]


def make_http():
    filings = [(a, "8-K", d) for a, d, _, _ in RELEASES]
    sub = fakes.submissions("ACME", filings)
    sub["filings"]["recent"]["items"] = [i for _, _, i, _ in RELEASES]
    http = fakes.FakeHttp()
    http.add(sec.TICKERS, {"0": {"cik_str": 42, "ticker": "ACME", "title": "ACME"}})
    http.add(sec.SUBMISSIONS.format(cik=CIK), sub)
    http.add(sec.COMPANY_FACTS.format(cik=CIK), fakes.company_facts("ACME", {"Revenues": [
        fakes.fact_row(100, "2022-01-01", "2022-12-31", "0000000042-23-000001", "2023-02-20", "10-K")]}))
    for acc, _, _, sentence in RELEASES:
        base = ARCH.format(acc=acc.replace("-", ""))
        http.add(base + "doc.htm", b"<p>Current report cover page for the registrant.</p>")
        http.add(base + "index.json", {"directory": {"item": [{"name": "doc.htm"}, {"name": "ex991.htm"}]}})
        http.add(base + "ex991.htm", f"<p>Results. {sentence} Other matters were discussed.</p>".encode())
    return http


def fake_llm(schema, system, user):
    """Plays the model: returns the outlook sentence it was shown, verbatim."""
    for _, _, _, sentence in RELEASES:
        if sentence in user and "%" in sentence:
            lo, hi = sentence.split(" growth")[0].split()[-3], sentence.split(" growth")[0].split()[-1]
            return Targets(targets=[Target(metric="dividend_per_share", metric_text="distributions per unit",
                                           low_text=lo, high_text=hi, horizon_text="through at least 2026",
                                           quote=sentence)]), None
    return Targets(targets=[]), None


def test_verify_rejects_unquoted_numbers():
    t = Target(metric="revenue", metric_text="revenue", low_text="10%", high_text="", horizon_text="", quote="Revenue grows 10% a year.")
    assert guidance.verify(t, "Revenue grows 10% a year.")[1] == []
    bad = t.model_copy(update={"low_text": "11%"})
    assert "'11%' not inside quote" in guidance.verify(bad, "Revenue grows 10% a year.")[1]
    assert guidance.verify(t, "Some other text.")[1] == ["quote not found"]


def test_guidance_ledger_and_replay(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    monkeypatch.setattr("riskprobe.llm.structured_call", fake_llm)
    http = make_http()
    src = sec.SecSource(http)
    data = src.load("ACME")
    targets, _ = guidance.latest_before(src, data.filings, "2023-08-31")
    assert len(targets) == 1 and targets[0].low == 12 and targets[0].horizon_year == 2026
    assert targets[0].evidence.published_at == "2023-07-25"  # newest statement before the date
    lg = Ledger("ACME", "ACME")
    for a in guidance.to_assumptions(targets, "2023-08-31"):
        lg.add(a)
    assert lg.assumptions[0].threshold.source == "disclosed"
    res = audit.run(lg, "2024-06-30", http)
    aa = res.audits[0]
    assert [(e.date, e.status) for e in aa.evaluations] == [
        ("2023-08-31", "supported"), ("2023-10-24", "weakened"), ("2024-01-25", "insufficient")]
    assert aa.first_warning.date == "2023-10-24" and aa.failure_type == "상황 변화"


def test_memo_targets_are_verified_against_the_memo(monkeypatch):
    memo = ["Thesis: distributions per unit compound.", "We continue to see 12% to 15% growth per year in distributions per unit through at least 2026."]
    monkeypatch.setattr("riskprobe.llm.structured_call", fake_llm)
    r = guidance.extract_targets(memo, "메모", "memo.txt", "2023-08-31", source="user")
    assert r.targets[0].evidence.source == "user"
    assert guidance.to_assumptions(r.targets, "2023-08-31", threshold_source="user")[0].threshold.source == "user"
