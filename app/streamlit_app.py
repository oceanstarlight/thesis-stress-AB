"""Streamlit UI: Probe (before investing) and Audit (after), on SEC point-in-time data.

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Streamlit Community Cloud keeps keys in st.secrets; copy top-level string values into the
# environment so riskprobe.config reads them like a local .env. Existing env vars win.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:  # noqa: BLE001 - no secrets file locally is normal
    pass

from riskprobe import audit, audit_report, config, guidance, llm, probe, report  # noqa: E402
from riskprobe.http import Http  # noqa: E402
from riskprobe.ledger import Ledger  # noqa: E402
from riskprobe.sources.sec import SecSource  # noqa: E402

st.set_page_config(page_title="RiskProbe", layout="wide")

LEDGER_DIR = config.DATA_DIR / "ledger"
PROBE_DEMOS = {  # label: (ticker or CIK, as-of)
    "AES 2025-06 (금리 경로)": ("AES", "2025-06-30"),
    "AMT 2025-06 (레버리지)": ("AMT", "2025-06-30"),
    "HE 2023-06 (산불 직전)": ("HE", "2023-06-30"),
    "XPLR 2023-06 (전망 하향 전)": ("1603145", "2023-06-30"),
}
AUDIT_DEMOS = {  # label: (ledger file, end)
    "HE: 산불 전 판단 → 2025-06": ("HE_2023-06-30.json", "2025-06-30"),
    "XPLR: 회사 전망(분배금 연 12~15%) → 2025-06": ("XPLR_guidance_2023-06-30.json", "2025-06-30"),
    "AES: 2023-06 판단 → 2025-06": ("AES_2023-06-30.json", "2025-06-30"),
}


@st.cache_resource
def http() -> Http:
    return Http()


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def run_probe(query: str, as_of: str, user_json: str) -> tuple[str, str, list[dict]]:
    res = probe.run(query, as_of, http(), json.loads(user_json))
    rows = [{"경로": s.result.label_ko, "EBITDA": s.ebitda_basis, "기준": s.threshold_label,
             "기준값": s.result.threshold.value if s.result.threshold else None, "현재": s.result.current,
             "기준 도달 충격": report.shock_text(s.result), "등급": s.result.grade or "-"} for s in res.scenarios]
    ledger_json = json.dumps(asdict(res.ledger), ensure_ascii=False, indent=2) if res.ledger else ""
    return report.render(res), ledger_json, rows


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def run_audit(ledger_json: str, end: str) -> tuple[str, list[dict]]:
    path = config.CACHE_DIR / "tmp_ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger_json, encoding="utf-8")
    res = audit.run(Ledger.load(path), end, http())
    series = [{"가정": aa.assumption.id, "공개일": e.date, "값": e.value, "기준": aa.assumption.threshold.value,
               "상태": e.status} for aa in res.audits for e in aa.evaluations]
    return audit_report.render(res), series


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def guidance_ledger(query: str, as_of: str) -> str:
    src = SecSource(http())
    data = src.load(query)
    targets, _ = guidance.latest_before(src, data.filings, as_of)
    lg = Ledger(query, data.name)
    for a in guidance.to_assumptions(targets, as_of):
        lg.add(a)
    return json.dumps(asdict(lg), ensure_ascii=False, indent=2)


def sidebar() -> None:
    st.sidebar.title("RiskProbe")
    st.sidebar.caption("투자 판단이 어떤 조건에서 틀리는지 찾고(Probe), 나중에 왜 틀렸는지 감사한다(Audit).")
    ua = config.env("SEC_USER_AGENT")
    st.sidebar.markdown(f"{'🟢' if ua and '@' in ua else '🔴'} SEC EDGAR (User-Agent)")
    p = llm.provider()
    st.sidebar.markdown(f"{'🟢' if p != 'none' else '⚪'} LLM: {p if p != 'none' else '없음 (공시 추출·해석 생략)'}")
    st.sidebar.divider()
    st.sidebar.markdown("- 기준일까지 **공개된 공시만** 사용\n- 숫자·판정은 코드, LLM은 문장 추출·해석만\n- 확률 대신 **깨지는 조건**과 남은 여유")


def probe_tab() -> None:
    st.subheader("Probe: 이 투자가 괜찮다는 판단은 어떤 조건에서 틀리는가")
    cols = st.columns(len(PROBE_DEMOS))
    for c, (label, (q, d)) in zip(cols, PROBE_DEMOS.items()):
        if c.button(label, width="stretch"):
            st.session_state.update(probe_q=q, probe_d=d, probe_go=True)
    st.session_state.setdefault("probe_q", "AES")
    st.session_state.setdefault("probe_d", date.today().isoformat())
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("종목코드 또는 CIK (미국 상장사)", key="probe_q")
    d = c2.text_input("판단 기준일 (YYYY-MM-DD)", key="probe_d")
    with st.expander("선택 입력 (공시에 없을 때만)"):
        e1, e2, e3, e4 = st.columns(4)
        total = e1.number_input("총차입금 (USD)", value=0.0, format="%.0f")
        floating = e2.number_input("변동금리 차입금 (USD)", value=0.0, format="%.0f")
        cov = e3.number_input("이자보상배율 기준 (배)", value=0.0)
        lev = e4.number_input("순차입금/EBITDA 기준 (배)", value=0.0)
    user = {k: v for k, v in {"total_debt": total, "floating_debt": floating, "interest_coverage": cov,
                              "net_debt_to_ebitda": lev}.items() if v}
    if st.button("Probe 실행", type="primary") or st.session_state.pop("probe_go", False):
        with st.spinner("공시 수집 → 기준일 스냅샷 → 연차보고서 추출 → 역산 (처음 실행은 30초 정도)"):
            md, ledger_json, rows = run_probe(q.strip(), d.strip(), json.dumps(user, sort_keys=True))
        st.session_state["probe_ledger"] = ledger_json
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        st.markdown(md)
        if ledger_json:
            st.download_button("가정 원장 내려받기 (JSON)", ledger_json, file_name=f"{q}_{d}.json")
            st.info("이 원장은 Audit 탭에서 '이번 Probe 결과'로 바로 감사할 수 있다.")


def audit_tab() -> None:
    st.subheader("Audit: 그 판단은 이후 공시에서 언제, 어떤 종류로 깨졌는가")
    mode = st.radio("감사할 판단", ["데모", "이번 Probe 결과", "기업 공식 전망으로 만들기", "원장 파일 올리기"], horizontal=True)
    ledger_json, end = "", date.today().isoformat()
    if mode == "데모":
        label = st.selectbox("데모 사례", list(AUDIT_DEMOS))
        f, end = AUDIT_DEMOS[label]
        path = LEDGER_DIR / f
        ledger_json = path.read_text(encoding="utf-8") if path.exists() else ""
    elif mode == "이번 Probe 결과":
        ledger_json = st.session_state.get("probe_ledger", "")
        if not ledger_json:
            st.warning("먼저 Probe 탭에서 실행해 줘.")
    elif mode == "기업 공식 전망으로 만들기":
        c1, c2 = st.columns(2)
        q = c1.text_input("종목코드 또는 CIK", value="1603145")
        d = c2.text_input("판단 기준일", value="2023-06-30")
        if st.button("전망 추출"):
            with st.spinner("기준일 전 200일 실적·공정공시에서 전망 문장 추출"):
                st.session_state["guidance_ledger"] = guidance_ledger(q.strip(), d.strip())
        ledger_json = st.session_state.get("guidance_ledger", "")
    else:
        up = st.file_uploader("가정 원장 JSON", type="json")
        ledger_json = up.read().decode("utf-8") if up else ""
    end = st.text_input("재생 종료일", value=end)
    if ledger_json:
        lg = json.loads(ledger_json)
        st.caption(f"{lg.get('name', '')} · 가정 {len(lg.get('assumptions', []))}개")
        if st.button("Audit 실행", type="primary"):
            with st.spinner("기준일 이후 공시를 하나씩 재생"):
                md, series = run_audit(ledger_json, end.strip())
            quant = [r for r in series if r["값"] is not None]
            if quant:
                st.line_chart(quant, x="공개일", y="값", color="가정")
            st.markdown(md)


def sources_tab() -> None:
    st.subheader("데이터·출처")
    p = config.ROOT / "SOURCES.md"
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "SOURCES.md 없음")


def main() -> None:
    sidebar()
    t1, t2, t3 = st.tabs(["Probe (투자 전)", "Audit (투자 후)", "데이터·출처"])
    with t1:
        probe_tab()
    with t2:
        audit_tab()
    with t3:
        sources_tab()


main()
