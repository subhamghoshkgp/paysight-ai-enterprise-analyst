import os
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from paysight.analyst import analyze, fmt
from paysight.data import BANKS, END, METHODS, START, build, quality
from paysight.model import executive_brief, model_plan
from paysight.plans import METRICS, QUESTIONS, Plan, interpret

st.set_page_config(
    page_title="PaySight AI · Payment intelligence", page_icon="◈", layout="wide"
)
st.markdown(
    """<style>
.stApp{background:#f7f9fc;color:#182a40} [data-testid=stSidebar]{background:#10263c}
[data-testid=stSidebar] h2,[data-testid=stSidebar] p,[data-testid=stSidebar] label{color:#ebf4ff}
[data-testid=stSidebar] [data-baseweb=select] *{color:#172e44}
h1,h2,h3{letter-spacing:-.035em}
[data-testid=stMetric]{background:white;border:1px solid #d8e2ec;border-top:3px solid #16857a;
border-radius:10px;padding:16px 18px;height:100%}
.block-container{max-width:1420px;padding-top:3rem}
</style>""",
    unsafe_allow_html=True,
)


@st.cache_resource
def snapshot():
    path = build()
    return path, quality(path)


@st.cache_data(max_entries=128)
def run(plan):
    return analyze(snapshot()[0], plan)


try:
    path, report = snapshot()
except (OSError, sqlite3.Error):
    st.error(
        "The payment snapshot could not be opened. Check the data directory and its permissions."
    )
    st.stop()

with st.sidebar:
    st.header("◈  PaySight AI")
    st.caption("Enterprise payments intelligence")
    page = st.radio("Workspace", ["Overview", "AI analyst", "Data quality"])
    st.divider()
    selected = st.date_input(
        "Analysis window",
        (END - timedelta(days=6), END),
        min_value=START,
        max_value=END,
    )
    method = st.multiselect("Payment method", METHODS)
    banks = st.multiselect("Bank", BANKS)
    mode = st.selectbox(
        "Analysis engine",
        ["Offline · deterministic"]
        + (["OpenAI · assisted"] if os.getenv("OPENAI_API_KEY") else []),
    )
    with st.expander("Metric definitions"):
        for label, _, definition in METRICS.values():
            st.caption(f"{label} · {definition}")
    st.caption(f"Synthetic snapshot · {START:%d %b} – {END:%d %b %Y}")
if len(selected) != 2:
    st.info("Choose both the start and end dates.")
    st.stop()
start, end = selected
filters = tuple((k, tuple(v)) for k, v in [("method", method), ("bank", banks)] if v)


def scoped(p):
    combined = dict(p.filters)
    for k, values in filters:
        choices = tuple(v for v in values if k not in combined or v in combined[k])
        if not choices:
            raise ValueError("The question conflicts with a sidebar filter.")
        combined[k] = choices
    return replace(p, filters=tuple(combined.items())).validate()


def evidence(r):
    p = r["plan"]
    with st.expander("Query evidence · SQL, parameters and returned rows"):
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
        legend_orientation="h",
    )
    fig.update_yaxes(rangemode="tozero", gridcolor="#e9edf2")
    st.plotly_chart(fig, width="stretch")


def caveats(r):
    n = int(r["grouped"].attempts.min())
    st.caption(
        f"Snapshot quality: {len(report['Duplicates'])} duplicate copies removed · {report['Pending']} pending attempts excluded · {len(report['Missing failure reasons'])} missing decline reasons retained as Unknown. Smallest returned group: {n:,} eligible attempts. These are descriptive snapshot measurements. Small cohorts can fluctuate sharply."
    )


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
    elif page == "Data quality":
        st.title("Data quality")
        st.caption("Snapshot-wide checks · before dashboard filters")
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
        st.caption("Ask your data. Understand your business.")

        def use_example():
            st.session_state.question = st.session_state.example

        st.selectbox(
            "Example investigations", QUESTIONS, key="example", on_change=use_example
        )
        question = st.text_input(
            "Business question", value=QUESTIONS[0], key="question", max_chars=700
        )
        submit = st.button("Run analysis", type="primary")
        context = (question, selected, filters, mode)
        if submit:
            st.session_state.pop("answer", None)
            with st.spinner("Resolving the question and running validated queries…"):
                p = scoped(
                    (model_plan if mode.startswith("OpenAI") else interpret)(
                        question, start, end
                    )
                )
                r = run(p)
                brief = ""
                if mode.startswith("OpenAI"):
                    try:
                        brief = executive_brief(question, r["facts"])
                    except ValueError as exc:
                        st.warning(str(exc))
                st.session_state.answer = (context, r, brief)
        if "answer" in st.session_state and st.session_state.answer[0] == context:
            _, r, brief = st.session_state.answer
            p = r["plan"]
            st.subheader("Executive summary")
            st.write(brief or r["facts"][0])
            st.caption(f"{p.start} – {p.end} · {mode} · {METRICS[p.metric][2]}")
            if p.intent != "summary":
                st.caption(
                    f"Compared with {p.previous} – {p.start - timedelta(days=1)}"
                )
            st.subheader("Observed facts")
            for fact in r["facts"][0 if brief else 1 :]:
                st.write("• " + fact)
            if len(r["facts"]) == 1:
                st.write(
                    "Eligible attempts and successful attempts are shown in the evidence table below."
                )
            frame = (
                r["grouped"].sort_values(p.metric, ascending=p.ascending)
                if p.dimension != "day"
                else r["grouped"]
            )
            chart(
                frame,
                "segment",
                p.metric,
                METRICS[p.metric][0],
                METRICS[p.metric][1],
                p.dimension == "day",
                "period" if p.intent != "summary" else None,
            )
            st.dataframe(
                frame[
                    ["period", "segment", "attempts", "successes", p.metric]
                    if p.metric not in ("attempts", "successes")
                    else ["period", "segment", "attempts", "successes"]
                ],
                hide_index=True,
            )
            if r["lenses"]:
                st.subheader("What drove the change?")
                st.caption(
                    "Each tab explains the same portfolio change from a different angle. Contributions across tabs overlap."
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
                        st.dataframe(table.style.format(precision=2), width="stretch")
            a, b = st.columns(2)
            with a:
                st.subheader("Hypothesis")
                st.write(r["hypothesis"])
            with b:
                st.subheader("Recommended action")
                st.write(r["action"])
            caveats(r)
            evidence(r)
except (ValueError, pd.errors.DatabaseError) as exc:
    st.error(str(exc))
