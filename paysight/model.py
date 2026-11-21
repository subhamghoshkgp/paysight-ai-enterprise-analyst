"""Opt-in Groq and OpenAI planner and evidence editor. Model output is always untrusted."""

import json
import os
from datetime import date
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .data import END, START
from .plans import DIMS, METRICS, VALUES, Plan


PROVIDERS = {
    "Groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ", "openai/gpt-oss-20b"),
    "OpenAI": ("https://api.openai.com/v1/chat/completions", "OPENAI", "gpt-4o-mini"),
}


def ask(instructions, payload, provider="OpenAI"):
    endpoint, prefix, default_model = PROVIDERS[provider]
    key = os.getenv(f"{prefix}_API_KEY")
    if not key:
        raise ValueError(f"{provider} is not configured. Choose offline mode.")

    request = Request(
        endpoint,
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PaySight-AI/1.0",
        },
        data=json.dumps(
            {
                "model": os.getenv(f"{prefix}_MODEL") or default_model,
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
    except HTTPError as exc:
        detail = {
            401: "rejected the server API key",
            403: "declined the API request (HTTP 403)",
            429: "reached its rate limit",
        }.get(exc.code, f"returned HTTP {exc.code}")
        if provider == "Groq" and exc.code == 403:
            try:
                error_code = json.loads(exc.read(8192))["error"]["code"]
            except (ValueError, TypeError, KeyError, OSError):
                error_code = None
            if error_code in ("model_permission_blocked_org", "model_permission_blocked_project"):
                scope = "organization" if error_code.endswith("_org") else "project"
                detail = f"reports that its {scope} settings block the configured model"
        raise ValueError(f"{provider} {detail}. Retry or choose offline mode.") from exc
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "The model request failed or returned invalid JSON. Retry or choose offline mode."
        ) from exc


def model_plan(question, start, end, provider="OpenAI", previous=None):
    rules = """Translate the question to a payments analysis plan. Return JSON with metric, dimension, intent
(summary, compare, investigate), start, end (ISO dates), filters (object mapping dimension to arrays of allowed
values), ascending (boolean). Compare uses immediately preceding equal window. Investigate is for why success rate
changed. Snapshot covers six weeks. 'Last week' means seven days ending at selected end. Use selected dates by default.
Merchant region is the region. GTV and ATV cover successful payments only. Unsupported questions, dimensions,
filters, multiple unrelated requests or unclear denominators must return an error field. For a follow-up, prior_plan gives the resolved cohort and dates. Retain its scope. If the user asks which
segment contributed to a success-rate change, use investigate with the requested dimension.
For an ambiguous ranking such as worst bank without a metric return an error. Never return SQL."""
    v = ask(
        rules,
        dict(
            question=question,
            metrics=METRICS,
            dimensions=DIMS,
            filter_values=VALUES,
            snapshot=[str(START), str(END)],
            selected=[str(start), str(end)],
            prior_plan=previous.as_context() if previous else None,
        ),
        provider,
    )
    try:
        if not isinstance(v, dict):
            raise TypeError()
        if "error" in v:
            raise ValueError("Please clarify your metric, segment or time period.")
        if set(v) != {"metric", "dimension", "intent", "start", "end", "filters", "ascending"}:
            raise TypeError()
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


def executive_brief(question, facts, provider="OpenAI"):
    """Constrained extractive generation keeps every possible numerical statement verified."""
    v = ask(
        "Compose an extractive executive explanation from the supplied observations. Return JSON with order, a list of one to three distinct zero-based integer sentence indexes in narrative order.",
        dict(question=question, observations=facts),
        provider,
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
