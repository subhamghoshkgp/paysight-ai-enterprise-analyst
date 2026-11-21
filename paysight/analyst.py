import pandas as pd

from .plans import METRICS
from .query import execute

LENSES = ("method", "bank", "category", "region")
SMALL_SAMPLE = 30


def contribution(value):
    """Retain full precision for calculations and suppress signed zero for display."""
    return "0.00" if round(float(value), 2) == 0 else f"{value:+.2f}"


def describe_driver(table, dimension, change):
    effects = table["Total (pp)"]
    segment = effects.idxmin() if change < 0 else effects.idxmax()
    effect = effects.loc[segment]
    direction = "downward" if effect < 0 else "upward"
    return segment, (f"By {dimension}, {segment} had the largest {direction} contribution "
                     f"({contribution(effect)} pp, including mix and within-segment change).")



SMALL_SAMPLE_ADVICE = (
    "Ordinary variation in a small number of outcomes could explain this result.",
    "Widen the date range and check whether the pattern persists before investigating an incident.",
)


def interpret_lens(table, dimension, change, warning):
    if warning:
        return *SMALL_SAMPLE_ADVICE, warning
    if round(float(change), 2) == 0:
        return ("The aggregate rate was stable at the displayed precision.",
                "Review the segment contributions for offsetting changes.", "")
    segment, _ = describe_driver(table, dimension, change)
    row = table.loc[segment]
    if min(row["Previous attempts"], row["Current attempts"]) < SMALL_SAMPLE:
        warning = (f"The {segment} comparison has {int(row['Previous attempts'])} previous and "
                   f"{int(row['Current attempts'])} current attempts. Its contribution is sensitive to individual outcomes.")
        return *SMALL_SAMPLE_ADVICE, warning
    if abs(row["Mix (pp)"]) > abs(row["Within (pp)"]):
        return (f"A shift in the share of attempts going to {segment} may explain part of the movement.",
                f"Compare {segment}’s share of attempts across the two periods "
                f"({row['Previous share (%)']:.1f}% to {row['Current share (%)']:.1f}%) and check where volume shifted.", "")
    return (f"Changes in the outcomes of attempts within {segment} may explain part of the movement.",
            f"Compare failures and recorded reasons within {segment} across both periods "
            "before drawing a conclusion about the cause.", "")


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
    frames = {}
    sources = []

    def read(dim):
        if dim in frames:
            return frames[dim]
        frame, trace = execute(path, plan, dim)
        frames[dim] = frame
        trace["id"] = f"Q{len(traces) + 1}"
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
    sources.append(("all", "Current", None))
    if plan.dimension != "all" and plan.intent != "investigate" and not ranked.empty:
        row = ranked.iloc[0]
        facts.append(
            f"{row.segment} had the {'lowest' if plan.ascending else 'highest'} {name.lower()} ({fmt(metric, row[metric])}) in the current window."
        )
        sources.append((plan.dimension, "Current", row.segment))
    lenses = {}
    lens_notes = {}
    headline = facts[0]
    driver_facts = []
    sample_warning = ""
    sample = totals.loc[totals.attempts.idxmin()]
    if metric.endswith("_rate") and sample.attempts < SMALL_SAMPLE:
        count = int(sample.attempts)
        sample_warning = (f"Small sample in the {sample.period.lower()} period: {count} eligible attempts. "
                          f"Changing one outcome moves that period’s rate by {100 / count:.2f} percentage points.")
    elif metric.endswith("_rate") and plan.dimension != "all" and not ranked.empty and ranked.iloc[0].attempts < SMALL_SAMPLE:
        row = ranked.iloc[0]
        sample_warning = f"The ranked segment {row.segment} has only {row.attempts:,} current attempts."

    if plan.intent != "summary":
        old = totals[totals.period == "Previous"].iloc[0]
        diff = current[metric] - old[metric]
        change = f"{contribution(diff)} pp" if metric.endswith("_rate") else fmt(metric, diff)
        if pd.isna(diff):
            headline = f"{name} could not be compared because one period has no defined value."
        elif round(float(diff), 2) == 0:
            headline = f"{name} was unchanged at the displayed precision ({fmt(metric, current[metric])})."
        else:
            direction = "rose" if diff > 0 else "fell"
            headline = f"{name} {direction} from {fmt(metric, old[metric])} to {fmt(metric, current[metric])} ({change})."
        if plan.intent == "investigate" and round(float(diff), 2) > 0:
            headline += " There was no decline over these dates."
        sources.insert(0, ("all", None, None))
        facts.insert(
            0,
            headline,
        )
    hypothesis = "The observed pattern may reflect customer or routing differences. The snapshot does not identify a causal mechanism."
    action = "Compare the same segment in an adjacent window and check its eligible attempt count."
    if plan.intent == "investigate":
        for dim in LENSES:
            lenses[dim] = decompose(read(dim))
        bymethod = lenses["method"]
        mix = bymethod["Mix (pp)"].sum()
        within = bymethod["Within (pp)"].sum()
        method_fact = (f"Payment-method mix accounted for {contribution(mix)} pp. "
                       f"Changes within methods accounted for {contribution(within)} pp.")
        facts.append(method_fact)
        sources.append(("method", None, None))
        driver_facts.append(method_fact)
        if round(float(diff), 2) != 0:
            banks = lenses["bank"]["Within (pp)"]
            bank = banks.idxmin() if diff < 0 else banks.idxmax()
            shift = banks.loc[bank]
            bank_fact = f"In the bank breakdown, {bank}'s within-bank rate change contributed {contribution(shift)} pp."
            facts.append(bank_fact)
            sources.append(("bank", None, None))
            driver_facts.append(bank_fact)
            if plan.dimension in LENSES:
                dim = plan.dimension
                segment, driver = describe_driver(lenses[dim], dim, diff)
                facts.insert(0, driver)
                sources.insert(0, (dim, None, None))
                driver_facts.insert(0, driver)
        for dim, table in lenses.items():
            lens_notes[dim] = interpret_lens(table, dim, diff, sample_warning)
        selected = plan.dimension if plan.dimension in LENSES else "method"
        hypothesis, action, lens_warning = lens_notes[selected]
        sample_warning = sample_warning or lens_warning
    if sample_warning and not lenses:
        hypothesis, action = SMALL_SAMPLE_ADVICE
    return dict(
        plan=plan,
        headline=headline,
        driver_facts=driver_facts,
        sample_warning=sample_warning,
        totals=totals,
        grouped=grouped,
        lenses=lenses,
        lens_notes=lens_notes,
        facts=facts,
        sources=sources,
        frames=frames,
        hypothesis=hypothesis,
        action=action,
        traces=traces,
    )
