import io
import json
from dataclasses import replace
from datetime import timedelta
from urllib.error import HTTPError

import pytest

from paysight.analyst import analyze
from paysight.data import END, START, build
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
    first = replace(p, start=START, end=START)
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
        answer = dict(previous.as_context(), dimension="bank") if "question" in payload and "metrics" in payload else {"order": [1]}
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
