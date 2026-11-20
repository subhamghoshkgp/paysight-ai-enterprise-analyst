"""Independent oracle starts at raw ingest and uses Python counters, never the SQL view."""

import sqlite3
from collections import defaultdict
from datetime import timedelta

import pytest

from paysight.analyst import analyze, decompose
from paysight.data import END, build, quality
from paysight.plans import QUESTIONS, Plan, interpret


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    return build(tmp_path_factory.mktemp("snapshot") / "fixture.sqlite")


@pytest.fixture(scope="module")
def oracle(snapshot):
    db = sqlite3.connect(snapshot)
    db.row_factory = sqlite3.Row
    banks = {r["id"]: r["name"] for r in db.execute("SELECT * FROM banks")}
    shops = {r["id"]: r for r in db.execute("SELECT * FROM merchants")}
    seen = {}
    for record in db.execute("SELECT * FROM raw_transactions ORDER BY rowid"):
        r = dict(record)
        r.update(
            bank=banks[r["bank_id"]],
            **{k: shops[r["merchant_id"]][k] for k in ("category", "region")},
        )
        r["reason"] = r["reason"] or "Unknown"
        seen.setdefault(r["id"], r)
    db.close()
    return [r for r in seen.values() if r["status"] in ("SUCCESS", "FAILED")]


# Independent expectations include the semantic plan as well as each resulting group.
CASES = [
    (0, "success_rate", "all", 7, True, {}),
    (1, "success_rate", "all", 7, False, {}),
    (2, "success_rate", "all", 7, True, {}),
    (3, "success_rate", "bank", 7, False, {}),
    (4, "failure_rate", "method", 7, False, {}),
    (5, "attempts", "day", 30, False, {}),
    (6, "failures", "category", 7, False, {}),
    (7, "success_rate", "method", 7, False, {"method": ["UPI", "Credit Card"]}),
    (8, "gtv", "region", 7, False, {}),
    (9, "failures", "reason", 7, False, {}),
    (10, "atv", "all", 7, False, {"method": ["Wallet"]}),
]


@pytest.mark.parametrize("index,metric,dimension,days,compare,filters", CASES)
def test_questions(index, metric, dimension, days, compare, filters, snapshot, oracle):
    plan = interpret(QUESTIONS[index], END - timedelta(days=6), END)
    assert (plan.metric, plan.dimension, plan.start, plan.end) == (
        metric,
        dimension,
        END - timedelta(days=days - 1),
        END,
    )
    assert (plan.intent != "summary") == compare
    result = analyze(snapshot, plan)
    expected = defaultdict(list)
    for r in oracle:
        if any(r[k] not in vs for k, vs in filters.items()) or (
            dimension == "reason" and r["status"] != "FAILED"
        ):
            continue
        if str(plan.start) <= r["day"] <= str(END):
            period = "Current"
        elif compare and str(plan.previous) <= r["day"] < str(plan.start):
            period = "Previous"
        else:
            continue
        expected[period, r.get(dimension, "Portfolio")].append(r)
    actual = result["grouped"].set_index(["period", "segment"])
    assert set(actual.index) == set(expected)
    for key, rows in expected.items():
        n = len(rows)
        success = [r for r in rows if r["status"] == "SUCCESS"]
        s = len(success)
        gtv = sum(r["paise"] for r in success) / 100
        metrics = dict(
            success_rate=100 * s / n,
            failure_rate=100 * (n - s) / n,
            atv=gtv / s if s else None,
            attempts=n,
            failures=n - s,
            gtv=gtv,
        )
        assert actual.loc[key, metric] == pytest.approx(metrics[metric])
    if index == 0:
        assert len(result["traces"]) == 5
        change = (
            actual.loc[("Current", "Portfolio"), metric]
            - actual.loc[("Previous", "Portfolio"), metric]
        )
        assert change < 0
        for frame in result["lenses"].values():
            assert frame["Total (pp)"].sum() == pytest.approx(change)
        assert result["lenses"]["method"]["Mix (pp)"].sum() < 0
        assert result["lenses"]["bank"]["Within (pp)"].idxmin() == "Northstar"


def test_quality_and_reproducibility(snapshot, tmp_path):
    other = build(tmp_path / "second.sqlite")
    assert other.read_bytes() == snapshot.read_bytes()
    q = quality(snapshot)
    assert q["Raw rows"] - q["Unique attempts"] == len(q["Duplicates"]) == 24
    assert len(q["Missing failure reasons"]) == 15 and not q["Orphan references"]
    assert all(copies == 2 for _, copies in q["Duplicates"])
    with sqlite3.connect(snapshot) as db:
        assert (
            db.execute("SELECT count(*) FROM eligible").fetchone()[0]
            == q["Unique attempts"] - q["Pending"]
        )


def test_missing_segment_convention():
    import pandas as pd

    frame = pd.DataFrame(
        [("Previous", "A", 10, 80), ("Current", "B", 5, 60)],
        columns=["period", "segment", "attempts", "success_rate"],
    )
    out = decompose(frame)
    assert out["Total (pp)"].sum() == pytest.approx(-20)
    assert out["Within (pp)"].sum() == 0


def test_empty_window(snapshot):
    with pytest.raises(ValueError, match="No eligible"):
        analyze(
            snapshot,
            Plan(
                "success_rate",
                "all",
                "summary",
                END,
                END,
                (("method", ("Wallet",)), ("method", ("UPI",))),
            ),
        )


@pytest.mark.parametrize(
    "question",
    [
        "hello",
        "Show pending success rate",
        "drop table banks",
        "volume last 500 days",
        "success rate on 2030-01-01",
    ],
)
def test_unsupported(question):
    with pytest.raises(ValueError):
        interpret(question, END, END)
