from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_evaluator_journey():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception and not app.error
    assert app.radio[0].options == ["AI analyst", "Overview"]
    assert app.radio[0].value == "AI analyst"
    assert app.text_input(key="question").label == "Business question"
    assert not app.code
    app.radio[0].set_value("Overview").run()
    assert len(app.get("plotly_chart")) == 5
    assert any(e.label.startswith("Data quality") for e in app.expander)
    assert any("24 duplicated" in w.value for w in app.warning)
    app.radio[0].set_value("AI analyst").run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert len(set(block.value for block in app.code)) == 5 and len(app.tabs) == 4
    assert any(e.label.startswith("View evidence") for e in app.expander)
    assert any("94.22%" in e.value and "86.59%" in e.value for e in app.markdown)


def test_invalid_question_clears_prior_result():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.button[0].click().run()
    app.text_input[0].set_value("What was the success rate for ImaginaryBank?").run()
    app.button[0].click().run()
    assert app.error and not app.code

def test_scoped_conversation():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button[0].click().run()
    app.text_input[1].set_value("Within UPI, which bank contributed most?")
    app.button[1].click().run()
    assert not app.error and not app.exception
    result = app.session_state.answer["result"]
    assert result["plan"].filters == (("method", ("UPI",)),)
    assert result["plan"].dimension == "bank"
    assert "Northstar" in result["facts"][0]
    app.text_input[1].set_value("Only Wallet")
    app.button[1].click().run()
    assert any("conflicts" in w.value for w in app.warning)
    assert app.session_state.answer["result"]["plan"] == result["plan"]


def test_clarifies_bank_ranking():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.text_input[0].set_value("Which bank performed worst?").run()
    app.button[0].click().run()
    assert app.info and not app.code
    app.radio(key="ranking_basis").set_value("Most failed attempts").run()
    app.button[0].click().run()
    assert not app.error and not app.exception
    plan = app.session_state.answer["result"]["plan"]
    assert (plan.metric, plan.dimension, plan.ascending) == ("failures", "bank", False)


def test_groq_brief_failure_preserves_evidence(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-test-fixture")

    def answer(instructions, payload, provider):
        assert provider == "Groq"
        if "observations" in payload:
            raise ValueError("Groq reached its rate limit.")
        return dict(metric="success_rate", dimension="all", intent="investigate",
                    start="2026-11-09", end="2026-11-15", filters={}, ascending=False)

    monkeypatch.setattr("paysight.model.ask", answer)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert any("rate limit" in warning.value for warning in app.warning)
    assert app.code and "86.59%" in app.session_state.answer["result"]["facts"][0]


def test_prior_release_answer_is_discarded():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.session_state["answer"] = {"context": ("old schema",), "result": {"facts": []}}
    app.run()
    assert not app.error and not app.exception and not app.code
    app.button[0].click().run()
    assert not app.error and not app.exception
    assert app.session_state.answer["result"]["sources"]

def test_automatic_routing_with_a_configured_key(monkeypatch):
    calls = []
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")

    def summarize(instructions, payload, provider):
        assert provider == "Groq" and "observations" in payload
        calls.append(payload["question"])
        return {"order": [0]}

    monkeypatch.setattr("paysight.model.ask", summarize)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    prompt = app.text_input[0]
    prompt.set_value("Show monthly transaction volume over the full history.").run()
    app.button[0].click().run()
    result = app.session_state.answer["result"]
    assert not calls and len(result["grouped"]) == 13
    assert result["grouped"].attempts.sum() == 358768
    assert app.session_state.answer["planner"] == "Direct SQL"
    why = "Why did our payment success rate drop last week?"
    app.text_input[0].set_value(why).run()
    app.button[0].click().run()
    assert calls == [why] and app.session_state.answer["brief"]
    app.text_input[1].set_value("Only UPI")
    app.button[1].click().run()
    assert calls == [why] and app.session_state.answer["planner"] == "Direct SQL"
