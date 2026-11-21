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
    why = "Why did our payment success rate decline last week?"
    app.text_input[0].set_value(why).run()
    app.button[0].click().run()
    assert calls == [why] and app.session_state.answer["brief"]
    app.text_input[1].set_value("Only UPI")
    app.button[1].click().run()
    assert calls == [why] and app.session_state.answer["planner"] == "Direct SQL"


def test_contextual_questions_and_followups(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")
    requests = []

    def respond(instructions, payload, provider):
        assert provider == "Groq"
        requests.append(payload)
        if "observations" in payload:
            return {"order": [0]}
        question = payload["question"]
        if "weather" in question:
            return {"error": "out_of_scope"}
        if "upii" in question:
            return {"error": "cohort", "suggestion": "UPI"}
        first, last = payload["selected"]
        inherited = payload["prior_plan"]
        return dict(metric="success_rate", dimension="bank" if inherited else "all",
                    intent="investigate" if inherited else "summary", start=first, end=last,
                    filters={"method": ["UPI"]}, ascending=False, explain=bool(inherited))

    monkeypatch.setattr("paysight.model.ask", respond)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_input(key="question").set_value("Of the UPI payments we tried, what share went through?").run()
    app.button[0].click().run()
    assert app.code and not app.error and len(requests) == 1
    assert app.session_state.answer["result"]["plan"].filters == (("method", ("UPI",)),)
    assert "Groq interpreted" in app.session_state.answer["planner"]

    app.text_input[1].set_value("Help me understand what was behind that movement across banks")
    app.button[1].click().run()
    assert not app.error and app.session_state.answer["brief"]
    assert requests[1]["prior_plan"]["filters"] == {"method": ("UPI",)}
    assert "observations" in requests[2]

    for question, expected in [("How is the weather near the bank?", "payment performance"),
                               ("sucess rate of upii", "Did you mean UPI")]:
        app.text_input(key="question").set_value(question).run()
        app.button[0].click().run()
        assert not app.code and not app.exception and "answer" not in app.session_state
        assert any(expected in e.value for e in app.error)


def test_single_day_overview_and_question_window():
    from datetime import date
    import json

    day = date(2026, 11, 12)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.date_input[0].set_value((day, day)).run()
    app.radio[0].set_value("Overview").run()
    layouts = [json.loads(chart.proto.spec)["layout"] for chart in app.get("plotly_chart")]
    daily = [layout for layout in layouts if layout["title"]["text"].startswith("Daily ")]
    assert len(daily) == 2
    for layout in daily:
        axis = layout["xaxis"]
        assert axis["ticktext"] == ["2026-11-12"] and axis["type"] == "category"
    app.radio[0].set_value("AI analyst").run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert any("Sidebar default" in c.value and "06 Nov" in c.value for c in app.caption)


def test_retry_preserves_driver_and_reuses_success(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")
    calls = []

    def brief(*args):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("Groq reached its rate limit.")
        return {"order": [1]}

    monkeypatch.setattr("paysight.model.ask", brief)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button[0].click().run()
    assert any("fell from" in x.value and "Northstar" in x.value for x in app.markdown)
    app.button[0].click().run()
    app.button[0].click().run()
    assert len(calls) == 2 and not app.exception and app.session_state.answer["brief"]
