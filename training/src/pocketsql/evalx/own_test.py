"""Check (and after edits, rehash) the hand-written own_test items.

Every gold query must execute, return a non-empty result that isn't all NULL, and be
deterministic: it must give the same result on a copy of the database whose tables
are stored in reverse row order (this catches ORDER BY ties and LIMIT boundaries).

`python -m pocketsql.evalx.own_test [--write]`: --write refreshes gold_result_hash.
"""

import argparse
import json
from pathlib import Path

import duckdb

from pocketsql.data import paths
from pocketsql.data.convert import quote_ident
from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx.compare import has_order_by, result_hash, results_match, run_duckdb
from pocketsql.evalx.sets import DEMO_DBS, db_path

FILES = (
    paths.EVAL_SETS / "own_test.jsonl",
    # Drafted items not kept in own_test; swap one in when an item is rejected.
    paths.EVAL_SETS / "own_test_reserve.jsonl",
)
DIFFICULTIES = ("easy", "medium", "hard", "extra")
FIELDS = ("id", "db_id", "question", "gold_sql", "gold_result_hash", "difficulty")


def reversed_copy(db_id: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads = 1")
    con.execute(f"ATTACH '{db_path(db_id)}' AS src (READ_ONLY)")
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = 'src' AND table_schema = 'main'"
    ).fetchall()
    for (t,) in tables:
        q = quote_ident(t)
        con.execute(
            f"CREATE TABLE main.{q} AS SELECT * FROM src.{q} ORDER BY rowid DESC"
        )
    con.execute("DETACH src")
    return con


def check_item(
    item: dict, con: duckdb.DuckDBPyConnection, rev: duckdb.DuckDBPyConnection
) -> tuple[str | None, str | None]:
    """Return (problem, result hash)."""
    sql = item["gold_sql"]
    try:
        rows = run_duckdb(con, sql)
        rev_rows = run_duckdb(rev, sql)
    except duckdb.Error as e:
        return f"error: {e}".splitlines()[0], None
    ordered = has_order_by(sql)
    if not rows:
        return "empty result", None
    if all(v is None for row in rows for v in row):
        return "all-NULL result", None
    if not results_match(rows, rev_rows, ordered):
        return "non-deterministic (ties or unordered LIMIT)", None
    return None, result_hash(rows, ordered)


def _run(items: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (problems, result hashes) by item id."""
    problems: dict[str, str] = {}
    hashes: dict[str, str] = {}
    by_db: dict[str, list[dict]] = {}
    for item in items:
        if tuple(item) != FIELDS:
            problems[item.get("id", "?")] = f"fields must be {FIELDS}"
        elif item["db_id"] not in DEMO_DBS or item["difficulty"] not in DIFFICULTIES:
            problems[item["id"]] = "unknown db_id or difficulty"
        else:
            by_db.setdefault(item["db_id"], []).append(item)
    for db_id, group in by_db.items():
        with (
            duckdb.connect(str(db_path(db_id)), read_only=True) as con,
            reversed_copy(db_id) as rev,
        ):
            for item in group:
                problem, h = check_item(item, con, rev)
                if problem:
                    problems[item["id"]] = problem
                elif h:
                    hashes[item["id"]] = h
    return problems, hashes


def check(items: list[dict]) -> dict[str, str]:
    problems, hashes = _run(items)
    for item in items:
        h = hashes.get(item.get("id", ""))
        if h and item.get("gold_result_hash") != h:
            problems[item["id"]] = f"gold_result_hash is stale (now {h})"
    ids = [i.get("id") for i in items]
    problems.update({i: "duplicate id" for i in ids if ids.count(i) > 1})
    return problems


def write_hashes(path: Path) -> None:
    items = read_jsonl(path)
    _, hashes = _run(items)
    for item in items:
        item["gold_result_hash"] = hashes.get(item["id"], "")
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps({k: item[k] for k in FIELDS}, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.own_test")
    parser.add_argument("--write", action="store_true", help="refresh result hashes")
    args = parser.parse_args(argv)
    total = 0
    for path in FILES:
        if args.write:
            write_hashes(path)
        items = read_jsonl(path)
        problems = check(items)
        for item_id, problem in problems.items():
            print(f"{path.name} {item_id}: {problem}")
        print(f"{path.name}: {len(items)} items, {len(problems)} problems")
        total += len(problems)
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
