import os
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from paysight.analyst import analyze, fmt
from paysight.data import BANKS, END, METHODS, START, build, quality
from paysight.model import executive_brief
from paysight.plans import METRICS, QUESTIONS, Plan, ambiguous_bank_ranking, follow_up, interpret, narrow, needs_explanation

st.set_page_config(
    page_title="PaySight AI · Payment intelligence", page_icon="◈", layout="wide"
)
st.markdown(
    """<style>
[data-testid="stMainMenu"], #MainMenu {display:none !important}
[data-testid="stMainBlockContainer"] {max-width:1240px;padding-top:2.6rem}
h1,h2,h3 {letter-spacing:-.035em}
[data-testid="stMetric"] {background:#fff;border:1px solid #d6e3e0;border-top:3px solid #13796a;
    border-radius:12px;padding:.85rem 1rem;height:100%}
[data-testid="stPlotlyChart"] {background:white;border:1px solid #d6e3e0;border-radius:12px;overflow:hidden}
[data-testid="stExpander"] {background:#fff;border-radius:10px}
[data-testid="stSidebar"] [data-testid="stExpander"] {background:transparent}
.st-key-answer_summary {background:#edf6f3;border-left:4px solid #13796a;
    padding:1rem 1.25rem;border-radius:8px}
[data-testid="stSidebar"] a {color:#b4e6df}
@media(max-width:700px) {
    [data-testid="stMainBlockContainer"] {padding-top:2rem}
    .st-key-answer_summary {padding:.75rem 1rem}
}
</style>""",
    unsafe_allow_html=True,
)


@st.cache_resource
def snapshot(start=START, end=END):
    path = build()
    return path, quality(path)


# Streamlit hashes this wrapper independently of the imported analysis implementation.
# Bump this version when the cached result format or its calculations change.
ANALYSIS_VERSION = 3


@st.cache_data(max_entries=128)
def cached_analysis(plan, version):
    return analyze(snapshot(START, END)[0], plan)


def run(plan):
    return cached_analysis(plan, ANALYSIS_VERSION)


try:
    path, report = snapshot(START, END)
except (OSError, sqlite3.Error):
    st.error(
        "The payment snapshot could not be opened. Check the data directory and its permissions."
    )
    st.stop()

with st.sidebar:
    st.header("PaySight AI", anchor=False)
    page = st.radio("Workspace", ["AI analyst", "Overview"])
    st.divider()
    selected = st.date_input(
        "Analysis window",
        (END - timedelta(days=6), END),
        min_value=START,
        max_value=END,
    )
    method = st.multiselect("Payment method", METHODS)
    banks = st.multiselect("Bank", BANKS)
    with st.expander("Metric definitions"):
        for label, _, definition in METRICS.values():
            st.caption(f"{label} · {definition}")
    st.caption(f"Synthetic data · {START:%d %b %Y} – {END:%d %b %Y}")
    st.markdown("[Dataset and definitions](https://github.com/subhamghoshkgp/paysight-ai-enterprise-analyst/tree/main/data)")
if len(selected) != 2:
    st.info("Choose both the start and end dates.")
    st.stop()
start, end = selected
filters = tuple((k, tuple(v)) for k, v in [("method", method), ("bank", banks)] if v)


def scoped(p):
    return narrow(p, filters)


def scope_label(p):
    return " · ".join(f"{k.title()} = {', '.join(v)}" for k, v in p.filters) or "All eligible attempts"


def claim_evidence(r):
    with st.expander("View evidence by finding"):
        index = st.selectbox("Finding", range(len(r["facts"])),
                             format_func=lambda i: r["facts"][i])
        dim, period, segment = r["sources"][index]
        trace = next(t for t in r["traces"] if t["dimension"] == dim)
        p = r["plan"]
        st.caption(f"Source: eligible · {scope_label(p)} · Current {p.start} to {p.end}")
        if p.intent != "summary" and period is None:
            st.caption(f"Previous {p.previous} to {p.start - timedelta(days=1)}")
        st.caption(METRICS[p.metric][2])
        rows = r["frames"][dim]
        if period:
            rows = rows[rows.period == period]
        if segment is not None:
            st.caption(f"Ranked segment: {segment}. All comparison rows are shown.")
            rows = rows.sort_values(p.metric, ascending=p.ascending)
        st.dataframe(rows, hide_index=True)
        if dim in r["lenses"] and period is None:
            st.caption("Derived from the rows above. Mix holds prior segment rates fixed. Within uses current segment shares.")
            st.dataframe(r["lenses"][dim].style.format(precision=2), width="stretch")
        st.code(trace["sql"], language="sql")
        st.write("Bound parameters", trace["parameters"])


def evidence(r, route=None):
    p = r["plan"]
    with st.expander("Query evidence"):
        if route:
            st.caption(f"Analysis method · {route}")
        st.write(
            "Sources: raw_transactions → attempts → eligible, joined to banks and merchants."
        )
        st.write(f"Current window: {p.start} to {p.end}, inclusive.")
        if p.intent != "summary":
            st.write(
                f"Previous window: {p.previous} to {p.start - timedelta(days=1)}, inclusive."
            )
        st.write("Filters:", dict(p.filters) or "All banks and methods")
        st.write("Definition:", METRICS[p.metric][2])
        for t in r["traces"]:
            st.caption(
                f"{t['dimension'].title()} · validated and executed · {t['rows']} aggregate rows"
            )
            st.code(t["sql"], language="sql")
            st.write("Bound parameters", t["parameters"])
        st.dataframe(r["totals"], hide_index=True)
        if p.dimension != "all":
            st.dataframe(r["grouped"], hide_index=True)


def chart(df, x, y, title, unit, line=False, color=None):
    fn = px.line if line else px.bar
    fig = fn(
        df,
        x=x,
        y=y,
        color=color,
        title=title,
        labels={x: "", y: unit, "period": "Period"},
        color_discrete_sequence=["#167b78", "#496fa5"],
        **({"markers": True} if line else {"barmode": "group"}),
    )
    fig.update_layout(
        height=310,
        margin=dict(l=12, r=16, t=48, b=15),
        plot_bgcolor="white",
        paper_bgcolor="white",
        title_font_size=17,
        showlegend=bool(color),
        legend=dict(orientation="h", yanchor="top", y=-0.2, x=0),
    )
    fig.update_yaxes(rangemode="tozero", gridcolor="#e9edf2")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "scrollZoom": False})


def cohort_quality(r):
    current = r["totals"].loc[r["totals"].period == "Current"].iloc[0]
    missing, failures = int(current.missing_reasons), int(current.failures)
    text = f"Selected cohort: {missing:,} of {failures:,} failed attempts have a missing reason."
    if missing:
        st.warning(text + " They count toward the failure rate and appear under Unknown in the reason breakdown.")


def caveats(r):
    cohort_quality(r)
    n = int(r["grouped"].attempts.min())
    with st.expander("Coverage and caveats"):
        st.write(f"The smallest returned group contains {n:,} eligible attempts. Rates in small cohorts can fluctuate sharply.")
        st.write(f"Across the full dataset, {len(report['Duplicates']):,} duplicate copies were removed and {report['Pending']:,} pending attempts were excluded. "
                 f"{len(report['Missing failure reasons']):,} failures have an unknown reason.")



try:
    if page == "Overview":
        st.title("Payment overview")
        st.caption(
            f"{start:%d %b %Y} – {end:%d %b %Y}  ·  INR  ·  Synthetic payment attempts"
        )
        p = scoped(Plan("success_rate", "day", "summary", start, end))
        r = run(p)
        row = r["totals"].iloc[0]
        cols = st.columns(4)
        for col, k in zip(cols, ["attempts", "success_rate", "failures", "gtv"]):
            col.metric(
                METRICS[k][0],
                fmt(k, row[k]) if k != "gtv" else f"₹{row[k] / 1e6:,.2f}M",
            )
        a, b = st.columns(2)
        with a:
            chart(
                r["grouped"],
                "segment",
                "success_rate",
                "Daily success rate",
                "Success (%)",
                True,
            )
        with b:
            chart(
                r["grouped"],
                "segment",
                "attempts",
                "Daily payment attempts",
                "Eligible attempts",
                True,
            )
        for col, dim, title in [
            (a, "method", "Payment methods"),
            (b, "bank", "Bank performance"),
        ]:
            with col:
                chart(
                    run(replace(p, dimension=dim))["grouped"],
                    "segment",
                    "success_rate",
                    title,
                    "Success (%)",
                )
        failures = (
            run(replace(p, dimension="reason", metric="failures"))
            if row.failures
            else None
        )
        if failures:
            chart(
                failures["grouped"],
                "segment",
                "failures",
                "Reasons for failed payments",
                "Failed attempts",
            )
        caveats(r)
        evidence(r)
        with st.expander("Data quality · full snapshot"):
            st.caption(f"{START} to {END} · all banks and methods")
            a, b, c, d = st.columns(4)
            for col, k in zip(
                (a, b, c, d),
                ("Raw rows", "Unique attempts", "Pending", "Orphan references"),
            ):
                col.metric(k, f"{report[k]:,}")
            st.warning(
                f"{len(report['Duplicates'])} duplicated transaction IDs · first ingested copy retained"
            )
            st.write(
                "Repeated attempts would inflate volume and could shift rates. The generator inserts one identical extra copy per affected ID."
            )
            st.dataframe(
                pd.DataFrame(
                    report["Duplicates"], columns=["Transaction ID", "Raw copies"]
                ),
                hide_index=True,
            )
            st.warning(
                f"{len(report['Missing failure reasons'])} failed attempts have a missing reason"
            )
            st.write(
                "These attempts count toward the failure rate. The reason breakdown groups them under Unknown."
            )
            st.dataframe(
                pd.DataFrame(
                    report["Missing failure reasons"], columns=["Affected transaction ID"]
                ),
                hide_index=True,
            )
    else:
        st.title("AI analyst")

        def use_example():
            if st.session_state.example:
                st.session_state.question = st.session_state.example

        with st.container(border=True):
            question = st.text_input(
                "Business question", value=QUESTIONS[0], key="question", max_chars=700
            )
            ranking = None
            if ambiguous_bank_ranking(question):
                ranking = st.radio(
                    "How should banks be ranked?", ["Lowest success rate", "Most failed attempts"],
                    index=None, key="ranking_basis",
                )
            actions, examples = st.columns([1, 3], vertical_alignment="bottom")
            submit = actions.button("Run analysis", type="primary", width="stretch")
            examples.selectbox(
                "Example questions", QUESTIONS, index=None, placeholder="Browse example questions",
                label_visibility="collapsed", key="example", on_change=use_example,
            )
        context = (ANALYSIS_VERSION, question, selected, filters, ranking)
        answer = st.session_state.get("answer")
        if answer and (not isinstance(answer, dict) or answer.get("context") != context):
            st.session_state.pop("answer", None)
            answer = None

        def save_result(plan, prompt, explain):
            result = run(scoped(plan))
            brief, warning = "", ""
            label = "Direct SQL"
            if explain and os.getenv("GROQ_API_KEY"):
                try:
                    brief = executive_brief(prompt, result["facts"], "Groq")
                    label = "SQL evidence + Groq explanation"
                except ValueError as exc:
                    warning = str(exc)
                    label = "SQL findings · Groq unavailable"
            elif explain:
                label = "SQL findings · Groq unconfigured"
            st.session_state.answer = dict(
                context=context, result=result, brief=brief, warning=warning,
                prompt=prompt, planner=label, explain=explain,
            )

        if submit:
            st.session_state.pop("answer", None)
            if ambiguous_bank_ranking(question) and not ranking:
                st.info("Choose the ranking measure above, then run the analysis.")
                st.stop()
            prompt = question
            if ranking:
                prompt = question.lower().replace("performed", "").replace("performing", "").replace("worst", "")
                prompt = prompt + (" lowest success rate" if ranking == "Lowest success rate" else " most failed attempts")
            with st.spinner("Analyzing payments…"):
                explain = needs_explanation(prompt)
                plan = interpret(prompt, start, end)
                save_result(plan, question, explain)
        answer = st.session_state.get("answer")
        if answer:
            results_panel = st.container()
            with st.form("followup_form", clear_on_submit=True):
                follow = st.text_input("Follow-up question", placeholder="Within UPI, which bank contributed most?", max_chars=700)
                drill = st.form_submit_button("Run follow-up")
            if drill:
                try:
                    explain = needs_explanation(follow)
                    next_plan = follow_up(follow, answer["result"]["plan"])
                    save_result(next_plan, follow, explain)
                    answer = st.session_state.answer
                except ValueError as exc:
                    st.warning(f"Follow-up could not run. {exc} Showing the last completed analysis.")
            with results_panel:
                r, brief = answer["result"], answer["brief"]
                p = r["plan"]
                summary = brief or r["facts"][0]
                with st.container(key="answer_summary"):
                    st.subheader("Executive summary", anchor=False)
                    if answer["prompt"] != question:
                        st.caption(answer["prompt"])
                    st.write(summary)
                    st.caption(f"{p.start:%d %b %Y} – {p.end:%d %b %Y} · {scope_label(p)}")
                    if p.intent != "summary":
                        earlier_end = p.start - timedelta(days=1)
                        st.caption(f"Compared with {p.previous:%d %b} – {earlier_end:%d %b %Y}")
                if answer["warning"]:
                    st.warning(answer["warning"] + " Showing verified findings.")
                remaining = [fact for fact in r["facts"] if fact not in summary]
                if remaining:
                    st.subheader("Observed findings", anchor=False)
                    for fact in remaining:
                        st.write(f"• {fact}")
                frame = (
                    r["grouped"].sort_values(p.metric, ascending=p.ascending)
                    if p.dimension not in ("day", "month")
                    else r["grouped"]
                )
                if p.dimension != "all" or p.intent != "summary":
                    chart(
                        frame,
                        "segment",
                        p.metric,
                        METRICS[p.metric][0],
                        METRICS[p.metric][1],
                        p.dimension in ("day", "month"),
                        "period" if p.intent != "summary" else None,
                    )
                if r["lenses"]:
                    st.subheader("What drove the change?")
                    st.caption(
                        "Each breakdown explains the same change. Contributions across tabs overlap."
                    )
                    for tab, (dim, table) in zip(
                        st.tabs(["Payment method", "Bank", "Merchant category", "Region"]),
                        r["lenses"].items(),
                    ):
                        with tab:
                            effects = table[["Mix (pp)", "Within (pp)"]].sum()
                            st.write(
                                f"Mix {effects.iloc[0]:+.2f} pp  ·  Within segments {effects.iloc[1]:+.2f} pp"
                            )
                            display = table[["Previous rate (%)", "Current rate (%)", "Mix (pp)", "Within (pp)", "Total (pp)"]]
                            st.dataframe(display.rename_axis(dim.title()).style.format(precision=2, na_rep="—"), width="stretch")
                if answer["explain"]:
                    a, b = st.columns(2)
                    with a:
                        st.subheader("Hypothesis")
                        st.write(r["hypothesis"])
                    with b:
                        st.subheader("Recommended action")
                        st.write(r["action"])
                caveats(r)
                claim_evidence(r)
                evidence(r, answer["planner"])
except (ValueError, pd.errors.DatabaseError) as exc:
    st.error(str(exc))
