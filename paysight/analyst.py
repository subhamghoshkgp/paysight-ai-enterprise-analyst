import pandas as pd

from .plans import METRICS
from .query import execute

LENSES = ("method", "bank", "category", "region")


def decompose(frame):
    """Rates in percentage points. Carry the observed rate across an absent period."""
    a = frame[frame.period == "Previous"].set_index("segment")
    b = frame[frame.period == "Current"].set_index("segment")
    if a.empty or b.empty:
        raise ValueError("Both periods need eligible attempts for attribution.")
    idx = a.index.union(b.index)
    n0 = a.attempts.reindex(idx, fill_value=0)
    n1 = b.attempts.reindex(idx, fill_value=0)
    p0, p1 = n0 / n0.sum(), n1 / n1.sum()
    r0 = a.success_rate.reindex(idx).fillna(b.success_rate)
    r1 = b.success_rate.reindex(idx).fillna(a.success_rate)
    # Center the mix contributions on the previous portfolio rate for interpretation.
    mix = (p1 - p0) * (r0 - (p0 * r0).sum())
    within = p1 * (r1 - r0)
    return pd.DataFrame(
        {
            "Previous attempts": n0,
            "Current attempts": n1,
            "Previous share (%)": 100 * p0,
            "Current share (%)": 100 * p1,
            "Previous rate (%)": a.success_rate,
            "Current rate (%)": b.success_rate,
            "Mix (pp)": mix,
            "Within (pp)": within,
            "Total (pp)": mix + within,
        }
    ).sort_values("Total (pp)")


def fmt(metric, x):
    if pd.isna(x):
        return "undefined"
    if metric in ("gtv", "atv"):
        return f"₹{x:,.2f}"
    if metric.endswith("_rate"):
        return f"{x:.2f}%"
    return f"{x:,.0f}"


def analyze(path, plan):
    plan.validate()
    traces = []

    def read(dim):
        frame, trace = execute(path, plan, dim)
        traces.append(trace)
        return frame

    totals = read("all")
    if totals.empty or (plan.intent != "summary" and len(totals) != 2):
        raise ValueError(
            "No eligible attempts in one or more requested periods. Widen the window or filters."
        )
    grouped = totals if plan.dimension == "all" else read(plan.dimension)
    if grouped.empty:
        raise ValueError("No matching segments in this window.")
    current = totals[totals.period == "Current"].iloc[0]
    metric = plan.metric
    name = METRICS[metric][0]
    ranked = grouped[grouped.period == "Current"].sort_values(
        metric, ascending=plan.ascending
    )
    facts = [
        f"{name}: {fmt(metric, current[metric])} across {current.attempts:,} eligible attempts."
    ]
    if plan.dimension != "all" and not ranked.empty:
        row = ranked.iloc[0]
        facts.append(
            f"{row.segment} had the {'lowest' if plan.ascending else 'highest'} {name.lower()} ({fmt(metric, row[metric])}) in the current window."
        )
    lenses = {}
    if plan.intent != "summary":
        old = totals[totals.period == "Previous"].iloc[0]
        diff = current[metric] - old[metric]
        change = f"{diff:+.2f} pp" if metric.endswith("_rate") else fmt(metric, diff)
        facts.insert(
            0,
            f"{name} moved from {fmt(metric, old[metric])} to {fmt(metric, current[metric])} ({change}).",
        )
    hypothesis = "The observed pattern may reflect customer or routing differences. The snapshot does not identify a causal mechanism."
    action = "Compare the same segment in an adjacent window and check its eligible attempt count."
    if plan.intent == "investigate":
        for dim in LENSES:
            lenses[dim] = decompose(read(dim))
        bymethod = lenses["method"]
        facts.append(
            f"Payment-method mix accounted for {bymethod['Mix (pp)'].sum():+.2f} pp. Changes within methods accounted for {bymethod['Within (pp)'].sum():+.2f} pp."
        )
        bank = lenses["bank"]["Within (pp)"].idxmin()
        shift = lenses["bank"].loc[bank, "Within (pp)"]
        facts.append(
            f"In the bank breakdown, {bank} had the smallest within-bank contribution ({shift:+.2f} pp)."
        )
        hypothesis = f"Routing or authorization changes at {bank} could explain its observed movement. Processor logs would be needed to test this."
        action = f"Compare {bank}'s timeout and authorization logs across the two windows, then check whether its method mix also changed."
    return dict(
        plan=plan,
        totals=totals,
        grouped=grouped,
        lenses=lenses,
        facts=facts,
        hypothesis=hypothesis,
        action=action,
        traces=traces,
    )
