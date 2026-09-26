import sqlite3

import duckdb

from pocketsql.data.convert import hardness, load_sqlite, transpile

NAMES = {"t", "u", "a", "b", "id", "name", "country"}


def test_double_quoted_strings_become_literals() -> None:
    got = transpile('SELECT name FROM t WHERE country = "France"', NAMES)
    assert got == "SELECT name FROM t WHERE country = 'France';"


def test_like_becomes_ilike_and_not_in_reads_naturally() -> None:
    got = transpile(
        'SELECT a FROM t WHERE name LIKE "%x%" AND id NOT IN (SELECT id FROM u)', NAMES
    )
    assert got == (
        "SELECT a FROM t WHERE name ILIKE '%x%' AND id NOT IN (SELECT id FROM u);"
    )


def test_bare_columns_join_group_by() -> None:
    got = transpile(
        "SELECT T1.name, count(*) FROM t AS T1 GROUP BY T1.id ORDER BY count(*) DESC",
        NAMES,
    )
    assert got == (
        "SELECT T1.name, COUNT(*) FROM t AS T1 GROUP BY T1.id, T1.name "
        "ORDER BY COUNT(*) DESC;"
    )


def test_plain_division_and_default_null_order() -> None:
    assert transpile("SELECT a / b FROM t ORDER BY a", NAMES) == (
        "SELECT a / b FROM t ORDER BY a;"
    )


def test_load_sqlite_repairs_loose_typing(tmp_path) -> None:
    src = tmp_path / "x.sqlite"
    with sqlite3.connect(src) as lite:
        lite.execute(
            "CREATE TABLE p (id INT, score INT, code TEXT, year TEXT, bad TEXT)"
        )
        lite.executemany(
            "INSERT INTO p VALUES (?, ?, ?, ?, ?)",
            [
                (1, 5, "02134", "2014", b"\xff".decode("latin-1")),
                (2, "", "10", "2015", "ok"),
            ],
        )
    notes = load_sqlite(src, tmp_path / "x.duckdb")
    con = duckdb.connect(str(tmp_path / "x.duckdb"), read_only=True)
    types = dict(
        con.execute("SELECT column_name, column_type FROM (DESCRIBE p)").fetchall()
    )
    assert types == {
        "id": "BIGINT",
        "score": "BIGINT",  # '' read as NULL
        "code": "VARCHAR",  # leading zero keeps it text
        "year": "BIGINT",  # numbers stored as text
        "bad": "VARCHAR",
    }
    assert con.execute("SELECT count(score) FROM p").fetchone() == (1,)
    assert any("empty strings" in n for n in notes)


def _sql(**over) -> dict:
    base = {
        "select": [False, [[0, [0, [0, 1, False], None]]]],
        "from": {"table_units": [["table_unit", 0]], "conds": []},
        "where": [],
        "groupBy": [],
        "having": [],
        "orderBy": [],
        "limit": None,
        "intersect": None,
        "union": None,
        "except": None,
    }
    return base | over


def test_hardness() -> None:
    assert hardness(_sql()) == "easy"
    two_cols = [False, [[0, [0, [0, 1, False], None]], [3, [0, [0, 2, False], None]]]]
    assert hardness(_sql(select=two_cols, limit=1)) == "medium"
    assert hardness(_sql(union=_sql(), limit=1)) == "hard"
    order = ["desc", [[0, [0, 1, False], None]]]
    assert hardness(_sql(union=_sql(), limit=1, orderBy=order)) == "extra"
