"""Click through the real Streamlit UI in demo mode (no API key)."""
import os

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(__file__), "app.py")


def test_ui_end_to_end(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.button(key="quick_0").click().run()
    assert at.text_input(key="topic").value == "Ohm's law"
    at.button(key="start").click().run()
    assert not at.exception
    assert len(at.chat_message) == 1
    at.chat_input(key="chat").set_value("Voltage is the electrical push, the potential difference in volts.").run()
    assert not at.exception
    assert len(at.chat_message) == 3
    at.button(key="finish").click().run()
    assert not at.exception
    assert any("Marking scheme" in m.value for m in at.markdown)
    at.button(key="again").click().run()
    assert not at.exception
    assert at.text_input(key="topic").value == "Ohm's law"
