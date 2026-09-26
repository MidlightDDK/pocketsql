"""Execute SQL and compare result sets (the EX definition in .claude/rules/data.md)."""

import datetime as dt
import decimal
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

TOL = 1e-6
_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")

Value = float | str | None
Rows = list[tuple[Value, ...]]


def run_sqlite(path: Path, sql: str, timeout: float = 20.0) -> list[tuple]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode(errors="replace")
    deadline = time.monotonic() + timeout
    con.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def run_duckdb(
    con: duckdb.DuckDBPyConnection, sql: str, timeout: float = 20.0
) -> list[tuple]:
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        return con.execute(sql).fetchall()
    finally:
        timer.cancel()


def normalize_value(v: object) -> Value:
    """Numbers (and numeric strings) become floats; dates and bytes become strings."""
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int | float | decimal.Decimal):
        return float(v)
    if isinstance(v, str):
        return float(v) if _NUMBER.fullmatch(v.strip()) else v
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, dt.datetime | dt.date | dt.time):
        return str(v)
    return str(v)


def normalize(rows: list[tuple]) -> Rows:
    return [tuple(normalize_value(v) for v in row) for row in rows]


def _key(row: tuple[Value, ...]) -> tuple:
    return tuple(
        (0, "")
        if v is None
        else (1, round(v, 6))
        if isinstance(v, float) and math.isfinite(v)
        else (2, str(v))
        for v in row
    )


def _same(a: Value, b: Value) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return a == b or math.isclose(a, b, rel_tol=TOL, abs_tol=TOL)
    return a == b


def results_match(a: list[tuple], b: list[tuple], ordered: bool) -> bool:
    x, y = normalize(a), normalize(b)
    if len(x) != len(y):
        return False
    if not ordered:
        x, y = sorted(x, key=_key), sorted(y, key=_key)
    return all(
        len(r) == len(s) and all(_same(u, v) for u, v in zip(r, s, strict=True))
        for r, s in zip(x, y, strict=True)
    )


def result_hash(rows: list[tuple], ordered: bool) -> str:
    keyed = [_key(r) for r in normalize(rows)]
    if not ordered:
        keyed.sort()
    return hashlib.sha256(json.dumps(keyed).encode()).hexdigest()[:16]


def has_order_by(sql: str, dialect: str = "duckdb") -> bool:
    tree = sqlglot.parse_one(sql, read=dialect)
    return isinstance(tree, exp.Query) and tree.args.get("order") is not None
