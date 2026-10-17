from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


def test_app_renders_without_network():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Probe (투자 전)", "Audit (투자 후)", "데이터·출처"]
    assert any("SEC EDGAR" in m.value for m in at.sidebar.markdown)
