from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_evaluator_journey():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception and not app.error
    assert len(app.metric) == 4 and len(app.get("plotly_chart")) == 5
    app.radio[0].set_value("AI analyst").run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert len(app.code) == 5 and len(app.tabs) == 4
    assert any("94.22%" in e.value and "86.59%" in e.value for e in app.markdown)
    app.radio[0].set_value("Data quality").run()
    assert not app.exception and "24 duplicated" in app.warning[0].value
    assert len(app.dataframe) == 2


def test_invalid_question_clears_prior_result():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.radio[0].set_value("AI analyst").run()
    app.button[0].click().run()
    app.text_input[0].set_value("What was the success rate for ImaginaryBank?").run()
    app.button[0].click().run()
    assert app.error and not app.code
