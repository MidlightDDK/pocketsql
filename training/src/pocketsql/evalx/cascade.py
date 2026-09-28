"""Cascade: the local model answers first, the large API model gets what looks wrong.

`python -m pocketsql.evalx.cascade [--report] [--markdown]` combines the released
q4f16 artifact's greedy and temperature-0.3 predictions with gpt-oss-120b's on the
sets both have (.claude/rules/evals.md). A local answer escalates when its SQL fails
to parse or run, or returns nothing (no rows, or only NULLs: every question is assumed
to have an answer); the `agree` rule also escalates when the sampled answer returns a
different result. --report writes the `cascade` section of evals/reports/latest.json.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import duckdb
import sqlglot

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx.compare import has_order_by, results_match, run_duckdb
from pocketsql.evalx.models import MODELS
from pocketsql.evalx.postprocess import clean_sql
from pocketsql.evalx.score import REPORT, TIMEOUT_S, connect, score_file
from pocketsql.evalx.sets import load_set

PREDICTIONS = paths.REPO / "evals" / "predictions"
LOCAL = ("pocketsql-0.5b-v2", "onnx-q4f16-webgpu")
SAMPLE_RUNTIME = "onnx-q4f16-webgpu-t0.3"  # the web app's retry temperature
BIG = ("gpt-oss-120b", "groq")
SETS = ("own_test", "spider_dev_100")
RULES = {"valid": ("error", "empty"), "agree": ("error", "empty", "disagree")}


def _run(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple] | None:
    try:
        return run_duckdb(con, sql, TIMEOUT_S) if sql else None
    except duckdb.Error:
        return None


def _ordered(*sqls: str) -> bool:
    try:
        return all(has_order_by(s) for s in sqls)
    except (sqlglot.errors.SqlglotError, RecursionError):
        return False


def escalation(con: duckdb.DuckDBPyConnection, sql: str, sample_sql: str) -> str | None:
    """Why the local answer escalates ("error", "empty", "disagree"), or None."""
    rows = _run(con, sql)
    if rows is None:
        return "error"
    if all(v is None for row in rows for v in row):  # also true for no rows
        return "empty"
    sample = _run(con, sample_sql)
    if sample is None or not results_match(rows, sample, _ordered(sql, sample_sql)):
        return "disagree"
    return None


def summarize(outcomes: list[dict], rule: str) -> dict:
    """outcomes: {reason, local_ex, big_ex, big_cost} per item."""
    n = len(outcomes)
    local = [o for o in outcomes if o["reason"] not in RULES[rule]]
    up = [o for o in outcomes if o["reason"] in RULES[rule]]
    ratio = lambda k, xs: round(sum(o[k] for o in xs) / len(xs), 4) if xs else None  # noqa: E731
    return {
        "rule": rule,
        "n": n,
        "answered_locally": round(len(local) / n, 4),
        "local_precision": ratio("local_ex", local),
        "ex": round(
            (sum(o["local_ex"] for o in local) + sum(o["big_ex"] for o in up)) / n, 4
        ),
        "local_ex": ratio("local_ex", outcomes),
        "big_ex": ratio("big_ex", outcomes),
        "api_calls_per_100": round(100 * len(up) / n, 1),
        "cost_per_query_usd": round(sum(o["big_cost"] for o in up) / n, 6),
        "escalations": {r: sum(o["reason"] == r for o in up) for r in RULES[rule]},
    }


def _file(model: str, runtime: str, set_name: str) -> Path:
    return PREDICTIONS / f"{model}__{runtime}__{set_name}.jsonl"


def cascade_set(set_name: str) -> list[dict]:
    local = {o["id"]: o for o in score_file(_file(*LOCAL, set_name))[1]}
    big = {o["id"]: o for o in score_file(_file(*BIG, set_name))[1]}
    sample = {p["id"]: p for p in read_jsonl(_file(LOCAL[0], SAMPLE_RUNTIME, set_name))}
    big_preds = {p["id"]: p for p in read_jsonl(_file(*BIG, set_name))}
    price_in, price_out = MODELS[BIG[0]]["price_per_m_usd"]
    outcomes = []
    for item in load_set(set_name):
        with connect(item["db_id"]) as con:
            sample_sql = clean_sql(sample.get(item["id"], {}).get("sql", ""))
            reason = escalation(con, local[item["id"]]["sql"], sample_sql)
        p = big_preds.get(item["id"], {})
        outcomes.append(
            {
                "reason": reason,
                "local_ex": local[item["id"]]["ex"],
                "big_ex": big[item["id"]]["ex"],
                "big_cost": (
                    (p.get("tokens_in") or 0) * price_in
                    + (p.get("tokens_out") or 0) * price_out
                )
                / 1e6,
            }
        )
    meta = {"set": set_name, "local": "/".join(LOCAL), "big": "/".join(BIG)}
    return [meta | summarize(outcomes, rule) for rule in RULES]


def markdown(rows: list[dict]) -> str:
    head = "| set | rule | local | local EX | cascade EX | big alone | API calls/100 |"
    lines = [head, "|" + "---|" * 7]
    for r in rows:
        lines.append(
            f"| {r['set']} | {r['rule']} | {r['answered_locally']:.0%} | "
            f"{r['local_precision']:.0%} | {r['ex']:.0%} | {r['big_ex']:.0%} | "
            f"{r['api_calls_per_100']:g} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.cascade")
    parser.add_argument("--report", action="store_true", help="update latest.json")
    parser.add_argument("--markdown", action="store_true", help="print a table")
    args = parser.parse_args(argv)
    rows = [
        r | {"scored": dt.date.today().isoformat()}
        for s in SETS
        for r in cascade_set(s)
    ]
    for r in rows:
        print(json.dumps(r))
    if args.markdown:
        print(markdown(rows))
    if args.report:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        report["cascade"] = rows
        REPORT.write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"updated {REPORT.relative_to(paths.REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
