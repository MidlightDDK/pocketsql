"""Score prediction files with one scorer for every runtime (.claude/rules/evals.md).

`python -m pocketsql.evalx.score evals/predictions/<model>__<runtime>__<set>.jsonl …
[--report] [--failures N] [--markdown]`: --report merges the results into
evals/reports/latest.json.
"""

import argparse
import datetime as dt
import json
import statistics
from collections import Counter
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx.compare import has_order_by, result_hash, results_match, run_duckdb
from pocketsql.evalx.models import MODELS
from pocketsql.evalx.own_test import check_item, reversed_copy
from pocketsql.evalx.postprocess import clean_sql
from pocketsql.evalx.sets import db_path, load_set

REPORT = paths.REPO / "evals" / "reports" / "latest.json"
API_RUNTIMES = ("groq",)
TIMEOUT_S = 10.0
DIFFICULTIES = ("easy", "medium", "hard", "extra")
TAGS = (
    "wrong column or table",
    "join error",
    "aggregation",
    "date/time functions",
    "dialect error",
    "hallucinated schema",
    "formatting",
    "other",
)
_DATE_FUNCS = {
    "year", "month", "day", "date_part", "datepart", "date_trunc", "datetrunc",
    "strftime", "strptime", "extract", "julianday", "date", "datetime", "now",
    "current_date", "date_diff", "datediff", "date_add", "age", "to_timestamp",
}  # fmt: skip
_SQL_START = ("select", "with", "from", "(", "values")


def connect(db_id: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        str(db_path(db_id)), read_only=True, config={"enable_external_access": False}
    )


def tie_dependent(item: dict, tries: int = 5) -> bool:
    """Gold whose result depends on ties or row order (~40 Spider-dev items): its hash
    is not reproducible, so it is scored against a fresh gold run instead. One check
    can pass by chance (parallel execution), so any of `tries` flagging it counts."""
    with connect(item["db_id"]) as con, reversed_copy(item["db_id"]) as rev:
        for _ in range(tries):
            problem, _ = check_item(item, con, rev)
            if problem and ("ties" in problem or "deterministic" in problem):
                return True
    return False


def _parse(sql: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql, read="duckdb")
    except (sqlglot.errors.SqlglotError, RecursionError):  # degenerate generations
        return None


def normalized(sql: str) -> str:
    tree = _parse(sql)
    text = tree.sql(dialect="duckdb", normalize=True) if tree else sql
    return " ".join(text.lower().rstrip("; \n").split())


def _tables(tree: exp.Expression) -> set[str]:
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table)} - ctes


def _funcs(tree: exp.Expression, kind: type) -> set[str]:
    return {type(f).__name__ for f in tree.find_all(kind)}


def _dates(tree: exp.Expression) -> set[str]:
    names = {f.sql_name().lower() for f in tree.find_all(exp.Func)}
    return names & _DATE_FUNCS


def error_tag(sql: str, error: str | None, gold_sql: str, n_cols: int | None) -> str:
    """Auto-tag a failure with the taxonomy in .claude/rules/evals.md."""
    if not sql or not sql.lower().startswith(_SQL_START):
        return "formatting"
    if error:
        low = error.lower()
        if "parser error" in low:
            return "dialect error"
        if "ambiguous reference" in low:
            return "join error"
        if "table with name" in low or ("binder error" in low and "not found" in low):
            return "hallucinated schema"
        if "does not have a column" in low or "referenced column" in low:
            return "hallucinated schema"
        if "group by" in low or "aggregate" in low:
            return "aggregation"
        if "function" in low and any(f in low for f in _DATE_FUNCS):
            return "date/time functions"
        return "dialect error"
    pred, gold = _parse(sql), _parse(gold_sql)
    if pred is None or gold is None:
        return "other"
    if _tables(pred) != _tables(gold):
        return "wrong column or table"
    gold_cols = len(gold.selects) if isinstance(gold, exp.Query) else None
    if n_cols is not None and gold_cols is not None and n_cols != gold_cols:
        return "wrong column or table"
    if len(list(pred.find_all(exp.Join))) != len(list(gold.find_all(exp.Join))):
        return "join error"
    if _funcs(pred, exp.AggFunc) != _funcs(gold, exp.AggFunc) or bool(
        pred.find(exp.Group)
    ) != bool(gold.find(exp.Group)):
        return "aggregation"
    if (_dates(pred) or _dates(gold)) and _dates(pred) != _dates(gold):
        return "date/time functions"
    return "other"


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


def score_file(path: Path) -> tuple[dict, list[dict]]:
    """Return (summary, per-item outcomes)."""
    model, runtime, set_name = path.stem.split("__")
    items = load_set(set_name)
    preds = {p["id"]: p for p in read_jsonl(path)}
    outcomes = []
    unstable = 0
    by_db: dict[str, list[dict]] = {}
    for item in items:
        by_db.setdefault(item["db_id"], []).append(item)
    for db_id, group in sorted(by_db.items()):
        with connect(db_id) as con:
            for item in group:
                gold = run_duckdb(con, item["gold_sql"], TIMEOUT_S)
                ordered = has_order_by(item["gold_sql"])
                if result_hash(gold, ordered) != item["gold_result_hash"]:
                    if not tie_dependent(item):
                        raise SystemExit(f"{item['id']}: gold result hash mismatch")
                    unstable += 1
                pred = preds.get(item["id"], {})
                sql = clean_sql(pred.get("sql", ""))
                error, rows = None, None
                try:
                    rows = run_duckdb(con, sql, TIMEOUT_S) if sql else None
                except duckdb.Error as e:
                    error = f"{type(e).__name__}: {e}".splitlines()[0]
                ok = rows is not None and results_match(gold, rows, ordered)
                n_cols = len(rows[0]) if rows else None
                outcomes.append(
                    {
                        "id": item["id"],
                        "difficulty": item["difficulty"],
                        "sql": sql,
                        "valid": rows is not None,
                        "ex": ok,
                        "exact": normalized(sql) == normalized(item["gold_sql"]),
                        "tag": None
                        if ok
                        else error_tag(sql, error, item["gold_sql"], n_cols),
                        "error": error,
                        "latency_ms": pred.get("latency_ms"),
                        "tokens_out": pred.get("tokens_out"),
                    }
                )
    n = len(outcomes)
    mean = lambda key: round(sum(o[key] for o in outcomes) / n, 4)  # noqa: E731
    latencies = [o["latency_ms"] for o in outcomes if o["latency_ms"] is not None]
    tokens = [o["tokens_out"] for o in outcomes if o["tokens_out"] is not None]
    price = MODELS.get(model, {}).get("price_per_m_usd")
    cost = (
        sum(
            (p.get("tokens_in") or 0) * price[0] + (p.get("tokens_out") or 0) * price[1]
            for p in preds.values()
        )
        / 1e6
        / len(preds)
        if price and preds
        else 0.0
    )
    by_diff = {}
    for d in DIFFICULTIES:
        sub = [o for o in outcomes if o["difficulty"] == d]
        if sub:
            by_diff[d] = {
                "n": len(sub),
                "ex": round(sum(o["ex"] for o in sub) / len(sub), 4),
            }
    tags = Counter(o["tag"] for o in outcomes if o["tag"])
    summary = {
        "model": model,
        "runtime": runtime,
        "set": set_name,
        "n": n,
        "missing": sum(1 for i in items if i["id"] not in preds),
        "ex": mean("ex"),
        "valid_sql": mean("valid"),
        "exact_match": mean("exact"),
        "latency_ms_p50": _pct(latencies, 0.5),
        "latency_ms_p95": _pct(latencies, 0.95),
        "tokens_out_mean": round(statistics.mean(tokens), 1) if tokens else None,
        "api_calls_per_100": 100 if runtime in API_RUNTIMES else 0,
        "cost_per_query_usd": round(cost, 6),
        "by_difficulty": by_diff,
        "errors": {t: tags[t] for t in TAGS if tags[t]},
        "gold_reran": unstable,
        "predictions": path.resolve().relative_to(paths.REPO, walk_up=True).as_posix(),
        "scored": dt.date.today().isoformat(),
    }
    return summary, outcomes


def update_report(summaries: list[dict]) -> None:
    report = (
        json.loads(REPORT.read_text(encoding="utf-8"))
        if REPORT.exists()
        else {"results": []}
    )
    key = lambda r: (r["set"], r["model"], r["runtime"])  # noqa: E731
    fresh = {key(s) for s in summaries}
    results = [r for r in report["results"] if key(r) not in fresh] + summaries
    report.update(
        updated=dt.date.today().isoformat(),
        models=MODELS,
        results=sorted(results, key=key),
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def markdown(summaries: list[dict]) -> str:
    head = "| set | model | runtime | EX | valid SQL | exact | p50 ms | p95 ms |"
    lines = [head, "|" + "---|" * 8]
    for s in summaries:
        lines.append(
            f"| {s['set']} | {s['model']} | {s['runtime']} | {s['ex']:.1%} | "
            f"{s['valid_sql']:.1%} | {s['exact_match']:.1%} | "
            f"{s['latency_ms_p50']} | {s['latency_ms_p95']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.score")
    parser.add_argument("predictions", nargs="+", type=Path, help="predictions .jsonl")
    parser.add_argument("--report", action="store_true", help="update latest.json")
    parser.add_argument("--failures", type=int, default=0, help="print N failures")
    parser.add_argument("--markdown", action="store_true", help="print a table")
    args = parser.parse_args(argv)
    summaries = []
    for path in args.predictions:
        summary, outcomes = score_file(path)
        summaries.append(summary)
        print(
            f"{path.name}: EX {summary['ex']:.1%}, valid {summary['valid_sql']:.1%}, "
            f"exact {summary['exact_match']:.1%}, n {summary['n']}, "
            f"errors {summary['errors']}"
        )
        for o in [o for o in outcomes if not o["ex"]][: args.failures]:
            print(f"  {o['id']} [{o['tag']}] {o['sql'][:160]} {o['error'] or ''}")
    if args.markdown:
        print(markdown(summaries))
    if args.report:
        update_report(summaries)
        print(f"updated {REPORT.relative_to(paths.REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
