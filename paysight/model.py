"""Opt-in OpenAI planner and evidence editor. Model output is always untrusted."""

import json
import os
from datetime import date
from urllib.request import Request, urlopen

from .data import END, START
from .plans import DIMS, METRICS, VALUES, Plan


def ask(instructions, payload):
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
            "Content-Type": "application/json",
        },
        data=json.dumps(
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                "response_format": {"type": "json_object"},
            }
        ).encode(),
    )
    try:
        with urlopen(request, timeout=15) as response:
            content = json.load(response)["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:
        raise ValueError(
            "The model request failed or returned invalid JSON. Retry or choose offline mode."
        ) from exc


def model_plan(question, start, end):
    rules = """Translate the question to a payments analysis plan. Return JSON with metric, dimension, intent
(summary, compare, investigate), start, end (ISO dates), filters (object mapping dimension to arrays of allowed
values), ascending (boolean). Compare uses immediately preceding equal window. Investigate is for why success rate
changed. Snapshot covers six weeks. 'Last week' means seven days ending at selected end. Use selected dates by default.
Merchant region is the region. GTV and ATV cover successful payments only. Unsupported questions, dimensions,
filters, multiple unrelated requests or unclear denominators must return an error field. Never return SQL."""
    v = ask(
        rules,
        dict(
            question=question,
            metrics=METRICS,
            dimensions=DIMS,
            filter_values=VALUES,
            snapshot=[str(START), str(END)],
            selected=[str(start), str(end)],
        ),
    )
    try:
        if "error" in v:
            raise ValueError("Please clarify your metric, segment or time period.")
        if not isinstance(v["ascending"], bool) or not isinstance(v["filters"], dict):
            raise TypeError()
        if any(not isinstance(vals, list) for vals in v["filters"].values()):
            raise TypeError()
        return Plan(
            v["metric"],
            v["dimension"],
            v["intent"],
            date.fromisoformat(v["start"]),
            date.fromisoformat(v["end"]),
            tuple((k, tuple(vals)) for k, vals in v["filters"].items()),
            v["ascending"],
        ).validate()
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(
            "The model returned an invalid analysis plan. Rephrase or use offline mode."
        ) from exc


def executive_brief(question, facts):
    """Constrained extractive generation keeps every possible numerical statement verified."""
    v = ask(
        "Compose an extractive executive explanation from the supplied observations. Return JSON with order, a list of one to three distinct zero-based integer sentence indexes in narrative order.",
        dict(question=question, observations=facts),
    )
    order = v.get("order") if isinstance(v, dict) else None
    if (
        not isinstance(order, list)
        or not 1 <= len(order) <= 3
        or any(type(i) != int or not 0 <= i < len(facts) for i in order)
        or len(set(order)) != len(order)
    ):
        raise ValueError(
            "Model summary unavailable. Verified observations are shown below."
        )
    return " ".join(facts[i] for i in order)
