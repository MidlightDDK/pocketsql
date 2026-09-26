"""SQLite → DuckDB: databases, gold SQL (sqlglot), and Spider's hardness label."""

import csv
import sqlite3
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.dialects.duckdb import DuckDB


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_sqlite(src: Path, dest: Path) -> list[str]:
    """Copy every SQLite table into a new DuckDB file; return fallback/failure notes.

    Tables are scanned with their declared types first. If loose SQLite typing breaks
    that, the table is loaded as VARCHAR (through Python when the text is not valid
    UTF-8) and each column is cast back to its declared type when every value allows
    it, reading empty strings as NULL if that is the only obstacle.
    """
    dest.unlink(missing_ok=True)
    lite = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    lite.text_factory = lambda b: b.decode(errors="replace")
    tables = [
        r[0]
        for r in lite.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    notes: list[str] = []
    con = duckdb.connect(str(dest))
    try:
        con.execute("INSTALL sqlite; LOAD sqlite")
        con.execute(f"ATTACH {quote_literal(str(src))} AS src (TYPE sqlite, READ_ONLY)")
        for t in tables:
            q = quote_ident(t)
            copy = f"CREATE TABLE {q} AS SELECT * FROM src.{q}"
            try:
                con.execute("SET sqlite_all_varchar = false")
                con.execute(copy)
                continue
            except duckdb.Error:
                pass
            try:
                declared = con.execute(f"DESCRIBE src.{q}").fetchall()
            except duckdb.Error as e:
                notes.append(f"table {t} failed: {str(e).splitlines()[0]}")
                continue
            try:
                con.execute("SET sqlite_all_varchar = true")
                con.execute(copy)
            except duckdb.Error:
                notes.append(f"table {t} copied through Python (invalid UTF-8)")
                _copy_via_csv(lite, con, t, [c for c, *_ in declared], dest)
            for col, typ, *_ in declared:
                if typ == "VARCHAR":
                    continue
                c = quote_ident(col)
                try:
                    con.execute(f"ALTER TABLE {q} ALTER {c} TYPE {typ}")
                    continue
                except duckdb.Error:
                    pass
                try:
                    con.execute(
                        f"ALTER TABLE {q} ALTER {c} TYPE {typ} USING NULLIF({c}, '')"
                    )
                    notes.append(f"column {t}.{col}: empty strings read as NULL")
                except duckdb.Error:
                    notes.append(f"column {t}.{col} kept as VARCHAR (declared {typ})")
        con.execute("DETACH src")
        for t in tables:
            notes += _numbers_from_text(con, t)
        con.execute("CHECKPOINT")
    finally:
        con.close()
        lite.close()
    return notes


_INT = r"-?(0|[1-9][0-9]{0,17})"
_DEC = r"-?(0|[1-9][0-9]*)\.[0-9]+"


def _numbers_from_text(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Retype VARCHAR columns whose every value is a canonical number (no leading
    zeros, signs, or spaces, so codes like '02134' stay text)."""
    q, notes = quote_ident(table), []
    for (col,) in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? AND data_type = 'VARCHAR'",
        [table],
    ).fetchall():
        c = quote_ident(col)
        n, ints, nums = con.execute(
            f"SELECT count({c}), count(*) FILTER (regexp_full_match({c}, '{_INT}')), "
            f"count(*) FILTER (regexp_full_match({c}, '{_INT}|{_DEC}')) FROM {q}"
        ).fetchone() or (0, 0, 0)
        typ = "BIGINT" if n and ints == n else "DOUBLE" if n and nums == n else None
        if typ:
            con.execute(f"ALTER TABLE {q} ALTER {c} TYPE {typ}")
            notes.append(f"column {table}.{col}: numbers stored as text read as {typ}")
    return notes


def _copy_via_csv(
    lite: sqlite3.Connection,
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
    dest: Path,
) -> None:
    # QUOTE_NONNUMERIC writes NULL as a bare empty field and every string quoted.
    tmp = dest.with_suffix(".csv")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        for row in lite.execute(f"SELECT * FROM {quote_ident(table)}"):
            w.writerow([None if v is None else str(v) for v in row])
    cols = ", ".join(f"{quote_literal(c)}: 'VARCHAR'" for c in columns)
    con.execute(
        f"CREATE TABLE {quote_ident(table)} AS SELECT * FROM read_csv("
        f"{quote_literal(str(tmp))}, header = false, columns = {{{cols}}}, "
        "quote = '\"', escape = '\"', allow_quoted_nulls = false)"
    )
    tmp.unlink()


def quote_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def schema_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'main'"
    ).fetchall()
    return {n.lower() for r in rows for n in r}


class _DuckDB(DuckDB):
    """DuckDB output with `x NOT IN (…)` and `x IS NOT NULL`, not `NOT x IN (…)`."""

    class Generator(DuckDB.Generator):
        def not_sql(self, expression: exp.Not) -> str:
            inner = expression.this
            kw = {exp.In: " IN", exp.Is: " IS", exp.Between: " BETWEEN"}.get(
                type(inner)
            )
            if kw:
                left, body = self.sql(inner, "this"), self.sql(inner)
                if body.startswith(left + kw + " "):
                    rest = body[len(left) + len(kw) :]
                    return (
                        f"{left} NOT{kw}{rest}"
                        if kw != " IS"
                        else f"{left} IS NOT{rest}"
                    )
            return super().not_sql(expression)


def transpile(sql: str, names: set[str]) -> str:
    """SQLite gold SQL → DuckDB, keeping SQLite semantics where DuckDB differs.

    - SQLite reads a double-quoted token that names no column as a string literal.
    - SQLite LIKE is case-insensitive; DuckDB's is not, so LIKE becomes ILIKE.
    - Plain `/` and DuckDB's default NULL ordering instead of sqlglot's guards (NULLIF,
      NULLS FIRST); the result check drops pairs where that changes the answer.
    - SQLite allows bare columns next to GROUP BY; they join the GROUP BY list, which
      is equivalent when they depend on the grouped key (the result check decides).
    """

    def literals(node: exp.Expression) -> exp.Expression:
        if (
            isinstance(node, exp.Column)
            and not node.table
            and isinstance(node.this, exp.Identifier)
            and node.this.quoted
            and node.name.lower() not in names
        ):
            return exp.Literal.string(node.name)
        if isinstance(node, exp.Div):
            node.set("safe", False)
        return node

    def ilike(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Like):
            return exp.ILike(this=node.this, expression=node.expression)
        if isinstance(node, exp.Ordered):
            node.set("nulls_first", False)  # DuckDB's default order; checked by result
        return node

    tree = sqlglot.parse_one(sql, read="sqlite").transform(literals).transform(ilike)
    for select in list(tree.find_all(exp.Select)):
        _complete_group_by(select)
    return tree.sql(dialect=_DuckDB) + ";"


def _complete_group_by(select: exp.Select) -> None:
    group = select.args.get("group")
    if not group or not group.expressions:
        return
    keys = {g.sql().lower() for g in group.expressions}
    aliases = {e.alias.lower() for e in select.expressions if isinstance(e, exp.Alias)}
    targets = list(select.expressions)
    if order := select.args.get("order"):
        targets += [o.this for o in order.expressions]
    if having := select.args.get("having"):
        targets.append(having.this)
    for target in targets:
        for col in list(target.find_all(exp.Column)):
            if col.find_ancestor(exp.Select) is not select:
                continue  # belongs to a subquery
            if not col.table and col.name.lower() in aliases:
                continue
            node, covered = col, False
            while node is not None and node is not select:
                if isinstance(node, exp.AggFunc) or node.sql().lower() in keys:
                    covered = True
                    break
                node = node.parent
            if not covered:
                keys.add(col.sql().lower())
                group.append("expressions", col.copy())


# Spider's official hardness (evaluation.py, Yu et al. 2018), quirks included,
# computed on the parsed `sql` field shipped with every Spider item.
_LIKE = 9  # WHERE_OPS.index("like")


def _has_agg(unit) -> bool:
    return unit[0] != 0


def _count_agg(units) -> int:
    return len([u for u in units if _has_agg(u)])


def _nested(sql: dict) -> list[dict]:
    nested = []
    for cond in sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]:
        nested += [v for v in (cond[3], cond[4]) if isinstance(v, dict)]
    nested += [sql[k] for k in ("intersect", "except", "union") if sql[k] is not None]
    return nested


def _component1(sql: dict) -> int:
    count = sum(bool(sql[k]) for k in ("where", "groupBy", "orderBy"))
    count += sql["limit"] is not None
    if sql["from"]["table_units"]:
        count += len(sql["from"]["table_units"]) - 1
    ao = sql["from"]["conds"][1::2] + sql["where"][1::2] + sql["having"][1::2]
    count += len([t for t in ao if t == "or"])
    conds = sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]
    return count + len([c for c in conds if c[1] == _LIKE])


def _others(sql: dict) -> int:
    agg = _count_agg(sql["select"][1]) + _count_agg(sql["where"][::2])
    agg += _count_agg(sql["groupBy"])
    if sql["orderBy"]:
        units = sql["orderBy"][1]
        agg += _count_agg([u[1] for u in units if u[1]] + [u[2] for u in units if u[2]])
    agg += _count_agg(sql["having"])
    return (
        (agg > 1)
        + (len(sql["select"][1]) > 1)
        + (len(sql["where"]) > 1)
        + (len(sql["groupBy"]) > 1)
    )


def hardness(sql: dict) -> str:
    c1, c2, others = _component1(sql), len(_nested(sql)), _others(sql)
    if c1 <= 1 and others == 0 and c2 == 0:
        return "easy"
    if (others <= 2 and c1 <= 1 and c2 == 0) or (c1 <= 2 and others < 2 and c2 == 0):
        return "medium"
    if (
        (others > 2 and c1 <= 2 and c2 == 0)
        or (2 < c1 <= 3 and others <= 2 and c2 == 0)
        or (c1 <= 1 and others == 0 and c2 <= 1)
    ):
        return "hard"
    return "extra"
