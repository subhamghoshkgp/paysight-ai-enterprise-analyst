import sqlite3

import pytest

from paysight.data import END, build, connect
from paysight.model import executive_brief, model_plan
from paysight.plans import QUESTIONS
from paysight.query import authorize, validate


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM eligible",
        "SELECT 1; SELECT 2",
        "SELECT * FROM raw_transactions",
        "CREATE TABLE x(a)",
        "ATTACH 'x' AS other",
        "SELECT status FROM eligible GROUP BY status",
        "SELECT private FROM eligible GROUP BY private LIMIT 500",
        "SELECT count(*) FROM eligible JOIN banks GROUP BY 1 LIMIT 500",
    ],
)
def test_sql_policy(sql):
    with pytest.raises(ValueError):
        validate(sql)


def test_authorizer(tmp_path):
    db = connect(build(tmp_path / "test.db"))
    db.set_authorizer(authorize)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("SELECT id FROM raw_transactions")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM attempts")
    db.close()


def test_model_contract(monkeypatch):
    plan = dict(
        metric="failure_rate",
        dimension="method",
        intent="summary",
        start=str(END),
        end=str(END),
        ascending=False,
        explain=False,
        filters={},
    )
    monkeypatch.setattr("paysight.model.ask", lambda *args: plan)
    assert model_plan(QUESTIONS[4], END, END).metric == "failure_rate"
    plan["dimension"] = "private"
    with pytest.raises(ValueError):
        model_plan("q", END, END)
    monkeypatch.setattr("paysight.model.ask", lambda *args: {"order": [1, 0]})
    assert executive_brief("q", ["First.", "Second."]) == "Second. First."
    monkeypatch.setattr("paysight.model.ask", lambda *args: {"order": [3]})
    with pytest.raises(ValueError):
        executive_brief("q", ["First."])


def test_semantic_plan_preserves_scope(monkeypatch):
    from paysight.model import resolve_request
    from paysight.plans import Plan, narrow

    monkeypatch.setenv("GROQ_API_KEY", "fixture")
    parent = Plan("attempts", "all", "summary", END, END, (("method", ("UPI",)),))
    response = dict(parent.as_context(), filters={}, explain=False)
    monkeypatch.setattr("paysight.model.ask", lambda *args: response)
    result, _, semantic = resolve_request("Can you unpack that number?", END, END, (), parent)
    assert semantic and result.filters == parent.filters
    response["filters"] = {"method": ["Wallet"]}
    with pytest.raises(ValueError, match="conflicts"):
        resolve_request("Tell me more about Wallet", END, END, (), parent)
    with pytest.raises(ValueError, match="Did you mean Wallet"):
        resolve_request("Tell me about payments", END, END, ())
    result, _, _ = resolve_request("Tell me about Wallet", END, END, parent.filters)
    with pytest.raises(ValueError, match="conflicts"):
        narrow(result, parent.filters)
    response["filters"] = {"method": []}
    with pytest.raises(ValueError, match="interpret"):
        resolve_request("Tell me about Wallet", END, END, ())
