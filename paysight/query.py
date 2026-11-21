"""Only compiled aggregate queries run. SQLite also checks resolved view access."""

import sqlite3
import time
from contextlib import closing

import pandas as pd
from sqlglot import exp, parse

from .data import connect


def compile_query(plan, dimension):
    plan.validate()
    from .plans import DIMS

    if dimension not in DIMS:
        raise ValueError("Unknown dimension")
    group = "'Portfolio'" if dimension == "all" else dimension
    compare = plan.intent != "summary"
    period = (
        "CASE WHEN day < ? THEN 'Previous' ELSE 'Current' END"
        if compare
        else "'Current'"
    )
    params = ([str(plan.start)] if compare else []) + [
        str(plan.previous if compare else plan.start),
        str(plan.end),
    ]
    where = ["day BETWEEN ? AND ?"]
    for name, values in plan.filters:
        where.append(f"{name} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    if dimension == "reason":
        where.append("status = 'FAILED'")
    sql = f"""SELECT {period} AS period, {group} AS segment,
       COUNT(*) AS attempts,
       SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
       SUM(CASE WHEN status = 'FAILED' AND reason = 'Unknown' THEN 1 ELSE 0 END) AS missing_reasons,
       SUM(CASE WHEN status = 'SUCCESS' THEN paise ELSE 0 END) AS successful_paise
FROM eligible
WHERE {" AND ".join(where)}
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 500"""
    return sql, params


def validate(sql):
    nodes = parse(sql, read="sqlite")
    if len(nodes) != 1 or type(nodes[0]) != exp.Select:
        raise ValueError("One aggregate SELECT required.")
    tree = nodes[0]
    tables = list(tree.find_all(exp.Table))
    if (
        len(tables) != 1
        or tables[0].name != "eligible"
        or tables[0].db
        or tables[0].catalog
    ):
        raise ValueError("Only the eligible analytical view is accessible.")
    if (
        any(tree.find_all(exp.Join, exp.Subquery, exp.With, exp.Union))
        or sum(1 for _ in tree.find_all(exp.Select)) != 1
    ):
        raise ValueError("Only a single aggregate scan is permitted.")
    if (
        tree.args.get("group") is None
        or tree.args.get("limit") is None
        or tree.args["limit"].expression.sql() != "500"
    ):
        raise ValueError("Bounded grouped results required.")
    allowed = {
        "day",
        "method",
        "bank",
        "category",
        "region",
        "reason",
        "status",
        "paise",
    }
    if any(c.name not in allowed for c in tree.find_all(exp.Column)):
        raise ValueError("Unknown analytical column.")


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (column or "").lower() in {
        "count",
        "sum",
        "coalesce",
    }:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and (
        table == "eligible"
        or (
            (source == "eligible" or column == "")
            and table in {"attempts", "merchants", "banks"}
        )
    ):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def execute(path, plan, dimension):
    sql, params = compile_query(plan, dimension)
    validate(sql)
    with closing(connect(path)) as db:
        db.set_authorizer(authorize)
        deadline = time.monotonic() + 3
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        frame = pd.read_sql_query(sql, db, params=params)
    frame["failures"] = frame.attempts - frame.successes
    frame["success_rate"] = 100 * frame.successes / frame.attempts
    frame["failure_rate"] = 100 * frame.failures / frame.attempts
    frame["gtv"] = frame.successful_paise / 100
    frame["atv"] = frame.gtv / frame.successes.replace(0, float("nan"))
    return frame, {
        "dimension": dimension,
        "sql": sql,
        "parameters": params,
        "rows": len(frame),
    }
