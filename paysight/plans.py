"""Shared contract for the offline parser, optional model and SQL compiler."""

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .data import BANKS, CATEGORIES, END, METHODS, REGIONS, START

METRICS = {
    "success_rate": ("Success rate", "%", "Successful / eligible attempts × 100"),
    "failure_rate": ("Failure rate", "%", "Failed / eligible attempts × 100"),
    "attempts": (
        "Eligible attempts",
        "attempts",
        "Unique successful and failed attempts",
    ),
    "successes": ("Successful attempts", "attempts", "Unique successful attempts"),
    "failures": ("Failed attempts", "attempts", "Unique failed attempts"),
    "gtv": ("Successful payment value", "₹", "Sum of successful payments, in INR"),
    "atv": (
        "Average successful payment",
        "₹",
        "Successful payment value / successful attempts",
    ),
}
DIMS = ("all", "bank", "method", "category", "region", "day", "month", "reason")
VALUES = {"bank": BANKS, "method": METHODS, "region": REGIONS, "category": CATEGORIES}
QUESTIONS = [
    "Why did our payment success rate decline last week?",
    "What was our payment success rate last week?",
    "Compare payment success rates for the last two weeks.",
    "Which banks have the lowest success rates?",
    "Which payment method has the highest failure rate?",
    "Show daily transaction volume for the last 30 days.",
    "Which merchant categories contribute most to failed transactions?",
    "Compare UPI and credit card performance.",
    "Which regions have the highest transaction amounts?",
    "What are the main drivers of payment failures?",
    "What was the average transaction value for Wallet last week?",
    "Show monthly transaction volume over the full history.",
]


@dataclass(frozen=True)
class Plan:
    metric: str
    dimension: str
    intent: str
    start: date
    end: date
    filters: tuple = ()
    ascending: bool = False

    def validate(self):
        if (
            self.metric not in METRICS
            or self.dimension not in DIMS
            or self.intent not in ("summary", "compare", "investigate")
        ):
            raise ValueError("Unsupported metric, dimension or analysis.")
        if not START <= self.start <= self.end <= END:
            raise ValueError(f"Choose dates within {START} through {END}.")
        if self.intent != "summary" and self.previous < START:
            raise ValueError(
                "The preceding comparison window falls outside the snapshot."
            )
        if self.intent == "investigate" and self.metric != "success_rate":
            raise ValueError("Investigations support payment success rate.")
        if self.dimension == "reason" and self.metric != "failures":
            raise ValueError("Failure-reason breakdowns support failed attempt counts.")
        for key, values in self.filters:
            if (
                key not in VALUES
                or not values
                or any(v not in VALUES[key] for v in values)
            ):
                raise ValueError("Unsupported filter.")
        return self

    def as_context(self):
        return dict(metric=self.metric, dimension=self.dimension, intent=self.intent,
                    start=str(self.start), end=str(self.end), filters=dict(self.filters),
                    ascending=self.ascending)

    @property
    def previous(self):
        return self.start - (self.end - self.start) - timedelta(days=1)


def needs_explanation(question):
    return bool(re.search(
        r"\b(why|explain|investigate|drivers?|caused?|root causes?|drove|behind|"
        r"contributed most to (?:the |this )?(?:drop|decline|change)|"
        r"contributed most(?=\s*[?!.]*$))\b", question.lower().strip()
    ))


def resolve_period(q, start, end):
    """Translate calendar periods before the bounded metric parser checks vocabulary."""
    if "over the full history" in q:
        return q.replace("over the full history", ""), START, END
    windows = {
        "last month": (end.replace(day=1) - timedelta(days=1)).replace(day=1),
        "this month": end.replace(day=1),
        "yesterday": end - timedelta(days=1),
        "today": end,
    }
    for phrase, first in windows.items():
        if re.search(r"\b" + phrase + r"\b", q):
            last = end.replace(day=1) - timedelta(days=1) if phrase == "last month" else end
            return q.replace(phrase, ""), first, first if phrase == "yesterday" else last
    for month in range(1, 13):
        name = calendar.month_name[month].lower()
        match = re.search(r"\b" + name + r" (\d{4})\b", q)
        if match:
            year = int(match[1])
            first = date(year, month, 1)
            last = first.replace(day=calendar.monthrange(year, month)[1])
            return q[:match.start()] + q[match.end():], first, last
    return q, start, end


def interpret(question, start, end):
    q = question.lower().strip()
    q, start, end = resolve_period(q, start, end)
    q = re.sub(r"\bby month\b", "monthly", q)
    if (
        not q
        or len(q) > 700
        or re.search(
            r"\b(delete|insert|select|sql|update|attach|export|settlement|forecast|median|percentile|refund|yesterday|today|month|quarter|year|hourly|excluding|exclude|except|without|pending)\b|\bdrop\s+(?:table|view|index)\b|;",
            q,
        )
    ):
        raise ValueError(
            "Please ask about eligible payment metrics within the snapshot. Use the date controls for a custom window."
        )
    # A bounded vocabulary prevents unknown cohort names from silently becoming portfolio queries.
    words = set(re.findall(r"[a-z]+", q))
    known = set(re.findall(r"[a-z]+", " ".join(QUESTIONS).lower()))
    known.update(
        "overall processed recorded had happen happened increasing decreasing decrease "
        "decreased increase increased spike rose rise fall fell go down up behind drove "
        "cause causes failing why monthly lower higher high low".split()
    )
    known.update(
        ["a", "an", "all", "at", "on", "in", "of", "between", "from", "through", "to", "by", "during", "per", "how", "many", "count", "counts", "total", "eligible", "successful", "successes", "attempts", "average", "mean", "gross", "value", "values", "atv", "gtv", "show", "me", "give", "us", "list", "rank", "ranked", "lowest", "highest", "worst", "best", "bottom", "smallest", "each", "day", "days", "trend", "over", "time", "past", "seven", "prior", "previous", "period", "week", "weeks", "versus", "vs", "compared", "compare", "change", "changed", "explain", "investigate", "caused", "approval", "percentage", "performance", "declined", "failed", "reason", "reasons", "region", "regionwide", "method", "methods", "bank", "segment", "segments", "category", "transaction", "merchant", "daily", "what", "which", "is", "are", "did", "does", "was", "were", "and", "for", "with", "please", "as", "paid", "payments", "most", "fewest", "largest", "top", "across", "more", "less", "fall", "drop", "decreasing", "dropped"]
    )
    for options in VALUES.values():
        for item in options:
            known.update(re.findall(r"[a-z]+", item.lower()))
    if words - known:
        raise ValueError(
            "Could not resolve: "
            + ", ".join(sorted(words - known))
            + ". Choose a listed cohort, a preset question or the date controls."
        )
    if re.search(r"\bto(p|tal) \d+|\bbottom \d+", q):
        raise ValueError("Rank the full breakdown with highest or lowest.")
    if re.search(r"\bmerchant(s)?\b", q) and not re.search(
        "categor|merchant segment|region", q
    ):
        raise ValueError("Choose merchant category or merchant region.")
    if re.search("success rate", q) and re.search(
        "failure rate|volume|average|amount", q
    ):
        raise ValueError("Ask about one metric at a time.")
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", q)
    if dates:
        if len(dates) > 2:
            raise ValueError("Specify a single day or one inclusive date range.")
        start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    elif re.search(r"\b(last|past|previous) (\d+) days?", q):
        days = int(re.search(r"\b(?:last|past|previous) (\d+) days?", q)[1])
        start = end - timedelta(days=days - 1)
    elif re.search(r"week|seven days", q):
        if re.search(r"weekend|weekly|\b(?:three|four|[3-9]) weeks", q):
            raise ValueError("Choose the desired window in the sidebar.")
        two_weeks = bool(re.search(r"(?:two|2) weeks", q))
        split_weeks = bool(re.search("compar|change|why|declin|versus|vs", q))
        start = end - timedelta(days=13 if two_weeks and not split_weeks else 6)
    elif re.search(r"\d|monday|sunday|october|november", q):
        raise ValueError("Use ISO dates (YYYY-MM-DD) or the sidebar date window.")
    filters = []
    for key, values in VALUES.items():
        found = tuple(
            v for v in values if re.search(r"\b" + re.escape(v.lower()) + r"\b", q)
        )
        if found:
            filters.append((key, found))
    dim = "all"
    for key, pattern in [
        ("month", "monthly"),
        ("day", "daily|each day|by day|trend|over time"),
        ("reason", "reason|drivers.*fail"),
        ("category", "categor|merchant segment"),
        ("bank", "\\bbanks?\\b"),
        ("region", "region"),
        ("method", "method"),
    ]:
        if re.search(pattern, q):
            dim = key
            break
    for key, values in filters:
        if len(values) > 1:
            dim = key
    if re.search("average|mean|atv", q):
        metric = "atv"
    elif re.search("amount|gross|gtv|transaction value", q):
        metric = "gtv"
    elif re.search("fail(ure|ed)? (rate|percentage)|decline rate", q):
        metric = "failure_rate"
    elif re.search("success rate|success percentage|performance|approval rate", q):
        metric = "success_rate"
    elif re.search("fail|declined attempts", q):
        metric = "failures"
    elif re.search("successful|successes", q):
        metric = "successes"
    elif re.search("volume|attempts|transaction count|(?:how many|total|count of) (?:transactions|payments)", q):
        metric = "attempts"
    else:
        raise ValueError(
            "Which metric do you mean? Try success rate, eligible volume, failed attempts or successful payment value."
        )
    investigate = metric == "success_rate" and bool(
        needs_explanation(q)
    )
    comparison = bool(
        re.search(
            "compared.*week|compare.*week|week.over.week|change|declin|versus.*week|vs.*week",
            q,
        )
    )
    if needs_explanation(q) and metric == "failures" and dim == "all" and not comparison:
        dim = "reason"
    if needs_explanation(q):
        movement = re.search(r"\b(increas\w*|decreas\w*|rose|fell|dropped|spike|changed?)\b", q)
        comparison = comparison or dim != "reason" or bool(movement)
    if dim == "all" and re.search(r"\bby\b", q):
        raise ValueError(
            "Choose a supported breakdown: bank, method, region, category or day."
        )
    return Plan(
        metric,
        dim,
        "investigate" if investigate else "compare" if comparison else "summary",
        start,
        end,
        tuple(filters),
        bool(re.search("lowest|worst|smallest|bottom", q)),
    ).validate()


def narrow(plan, filters):
    """Intersect scope, including filters set by the sidebar or a parent analysis."""
    combined = dict(plan.filters)
    for key, values in filters:
        choices = tuple(v for v in values if key not in combined or v in combined[key])
        if not choices:
            raise ValueError("The requested cohort conflicts with the active filters.")
        combined[key] = choices
    return replace(plan, filters=tuple(combined.items())).validate()


def follow_up(question, previous, planner=None):
    """Apply common drill-downs exactly. More general follow-ups may use a provider."""
    q = question.strip().lower().rstrip("?.!").strip()
    if not q:
        raise ValueError("Enter a follow-up question.")
    cohort = re.fullmatch(r"(?:only|within|just|filter to) (.+?)(?: only)?", q)
    if cohort:
        for key, values in VALUES.items():
            for value in values:
                if value.lower() == cohort[1]:
                    return narrow(previous, ((key, (value,)),))
    contribution = re.fullmatch(
        r"(?:within (.+?),\s*)?which (bank|method|region|category) contributed most"
        r"(?: to (?:the |this )?(?:decline|drop|change))?", q
    )
    if contribution:
        if previous.metric != "success_rate" or previous.intent == "summary":
            raise ValueError("Start with a comparison of success rates across two periods.")
        plan = replace(previous, dimension=contribution[2], intent="investigate")
        if contribution[1]:
            return follow_up("only " + contribution[1], plan)
        return plan.validate()
    breakdown = re.fullmatch(r"(?:break (?:it |that )?down by|group by|by) (bank|method|region|category|day|month)", q)
    if breakdown:
        return replace(previous, dimension=breakdown[1]).validate()
    if q in {"why", "why did it change", "why did it drop", "explain that change"}:
        intent = "investigate" if previous.metric == "success_rate" else "compare"
        return replace(previous, intent=intent).validate()
    if planner:
        candidate = planner(question, previous.start, previous.end, previous=previous)
        if (candidate.start, candidate.end) != (previous.start, previous.end):
            raise ValueError("Use a new business question to change the comparison dates.")
        return narrow(candidate, previous.filters)
    candidate = interpret(question, previous.start, previous.end)
    if (candidate.start, candidate.end) != (previous.start, previous.end):
        raise ValueError("Start a new business question to change dates.")
    return narrow(candidate, previous.filters)


def ambiguous_bank_ranking(question):
    q = question.lower()
    return (bool(re.search(r"\bbanks?\b", q) and re.search(r"\bworst\b", q))
            and not re.search(r"rate|count|volume|value|amount|attempt|failure|success|timeout", q))
