from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


def test_app_renders_without_network():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["통합 검토", "상세: Probe (투자 전)", "상세: Watch (보유 중)", "상세: Audit (투자 후)", "데이터·출처"]
    assert any("SEC EDGAR" in m.value for m in at.sidebar.markdown)
