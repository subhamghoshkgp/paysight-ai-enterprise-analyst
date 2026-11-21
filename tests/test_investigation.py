import io
import json
from dataclasses import replace
from datetime import timedelta
from urllib.error import HTTPError

import pytest

from paysight.analyst import analyze
from paysight.data import DEMO_START, END, build
from paysight.model import executive_brief, model_plan
from paysight.plans import QUESTIONS, follow_up, interpret


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    return build(tmp_path_factory.mktemp("investigation") / "snapshot.sqlite")


def test_upi_contribution_and_evidence(snapshot):
    initial = interpret(QUESTIONS[0], END, END)
    upi = follow_up("Only UPI", initial)
    bank = follow_up("Which bank contributed most?", upi)
    assert bank == follow_up("Within UPI, which bank contributed most?", initial)
    assert (bank.start, bank.end, bank.filters) == (initial.start, END, (("method", ("UPI",)),))
    r = analyze(snapshot, bank)
    assert len(r["facts"]) == len(r["sources"])
    assert r["sources"][0] == ("bank", None, None)
    assert {t["dimension"] for t in r["traces"]} == set(r["frames"])
    assert r["totals"].set_index("period").attempts.to_dict() == {"Current": 3859, "Previous": 1581}
    assert r["lenses"]["bank"]["Total (pp)"].idxmin() == "Northstar"
    assert "Northstar" in r["facts"][0]
    with pytest.raises(ValueError, match="conflicts"):
        follow_up("Only Wallet", bank)
    with pytest.raises(ValueError, match="dates"):
        follow_up("change dates", bank, lambda *a, **kw: replace(bank, start=bank.start + timedelta(days=1)))


def test_filtered_missing_reasons(snapshot):
    p = interpret(QUESTIONS[1], END, END)
    assert analyze(snapshot, p)["totals"].iloc[0].missing_reasons == 0
    first = replace(p, start=DEMO_START, end=DEMO_START)
    defects = analyze(snapshot, first)["totals"].iloc[0].missing_reasons
    assert defects == 15
    upi = follow_up("Only UPI", first)
    assert 0 < analyze(snapshot, upi)["totals"].iloc[0].missing_reasons < defects


def test_groq_transport_and_verified_brief(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    previous = follow_up("Only UPI", interpret(QUESTIONS[0], END, END))
    calls = []

    def respond(req, timeout):
        assert req.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert req.get_header("Authorization") == "Bearer test-fixture"
        body = json.loads(req.data)
        assert body["model"] == "test-model" and timeout == 15
        payload = json.loads(body["messages"][1]["content"])
        calls.append(payload)
        answer = dict(previous.as_context(), dimension="bank", explain=True) if "question" in payload and "metrics" in payload else {"order": [1]}
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(answer)}}]}).encode())

    monkeypatch.setattr("paysight.model.urlopen", respond)
    plan = model_plan("Break it down by bank", previous.start, END, "Groq", previous)
    assert plan.filters == previous.filters and plan.dimension == "bank"
    assert calls[0]["prior_plan"]["filters"] == {"method": ["UPI"]}
    assert executive_brief("Summarize", ["First fact.", "Second fact."], "Groq") == "Second fact."


def test_groq_rate_limit(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")

    def limited(req, timeout):
        raise HTTPError(req.full_url, 429, "limited", {}, None)

    monkeypatch.setattr("paysight.model.urlopen", limited)
    with pytest.raises(ValueError, match="rate limit"):
        model_plan("Last week's success rate?", END, END, "Groq")


def test_calendar_lookup_and_explanation_routes():
    from datetime import date

    from paysight.plans import needs_explanation

    lookup = "How many transactions were processed last month?"
    assert not needs_explanation(lookup)
    p = interpret(lookup, END, END)
    assert (p.metric, p.start, p.end) == ("attempts", date(2026, 10, 1), date(2026, 10, 31))
    march = interpret("What was our overall success rate in March 2026?", END, END)
    assert (march.start, march.end) == (date(2026, 3, 1), date(2026, 3, 31))
    why = "Why did the UPI success rate decrease?"
    assert needs_explanation(why)
    assert interpret(why, END, END).intent == "investigate"
    assert interpret("Why did failures increase?", END, END).intent == "compare"


def test_direction_and_small_sample(snapshot):
    from datetime import date
    from paysight.plans import Plan

    first = date(2026, 11, 14)
    plan = Plan("success_rate", "all", "investigate", first, first,
                (("method", ("UPI",)), ("bank", ("Northstar",))))
    result = analyze(snapshot, plan)
    assert "rose from 64.39% to 70.00%" in result["headline"]
    assert "no decline" in result["headline"]
    day = date(2026, 11, 15)
    wallet = replace(plan, start=day, end=day, filters=(("method", ("Wallet",)), ("bank", ("Northstar",))))
    result = analyze(snapshot, wallet)
    assert "-13.24 pp" in result["headline"]
    assert "16 eligible attempts" in result["sample_warning"] and "6.25" in result["sample_warning"]
    assert all("Widen" in action for _, action, _ in result["lens_notes"].values())


def test_lens_advice_and_display_precision(snapshot):
    from paysight.analyst import contribution

    r = analyze(snapshot, interpret(QUESTIONS[0], END, END))
    assert "UPI" in r["lens_notes"]["method"][1]
    assert "Northstar" in r["lens_notes"]["bank"][1]
    assert all("smallest" not in fact for fact in r["facts"])
    assert contribution(-0.0001) == "0.00" and contribution(-0.012) == "-0.01"
    assert all(r["lens_notes"][dim][1] for dim in ("category", "region"))


def test_group_cap_detects_overflow(snapshot, monkeypatch):
    from paysight.query import execute

    monkeypatch.setattr("paysight.query.MAX_GROUPS", 1)
    plan = interpret(QUESTIONS[1], END, END)
    assert len(execute(snapshot, plan, "all")[0]) == 1
    with pytest.raises(ValueError, match="exceeds 1"):
        execute(snapshot, plan, "method")
