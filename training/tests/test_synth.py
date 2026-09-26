import duckdb

from pocketsql.synth.__main__ import data_notes, finalize, to_train_rows
from pocketsql.synth.filters import (
    dedupe,
    one_line,
    plain_text,
    same_result_as_test,
    unordered_limit,
    vote,
)


def test_one_line_drops_fences_comments_and_extra_statements() -> None:
    text = (
        "```sql\nSELECT a,  -- note\n  'x  y'\nFROM t /* c */ WHERE b = 1;\n"
        "SELECT 2;\n```"
    )
    assert one_line(text) == "SELECT a, 'x  y' FROM t WHERE b = 1;"
    assert one_line("") == ""


def test_plain_text_replaces_typographic_characters() -> None:
    assert plain_text("species‑island  it’s “x”") == ('species-island it\'s "x"')


def test_vote_needs_two_agreeing_candidates_and_prefers_the_shortest() -> None:
    assert vote([("SELECT a AS x;", "h1"), ("SELECT a;", "h1"), ("S;", "h2")]) == (
        "SELECT a;",
        2,
    )
    assert vote([("a;", "h1"), ("b;", "h2"), ("c;", None)]) == (None, 1)
    assert vote([("a;", None)]) == (None, 0)


def _row(i: str, q: str, sql: str, db: str = "db", h: str = "r") -> dict:
    return {"id": i, "db_id": db, "question": q, "sql": sql, "result_hash": h}


def test_dedupe_drops_repeats_and_near_duplicates() -> None:
    kept, dropped = dedupe(
        [
            _row("a", "How many albums are there?", "SELECT count(*) FROM album;"),
            _row("b", "how many albums are there", "SELECT count(1) FROM album;"),
            _row("c", "Count the albums.", "select COUNT(*) from album"),
            _row("d", "How many albums are there?", "SELECT 1;", db="other"),
        ]
    )
    assert [r["id"] for r in kept] == ["a", "d"]
    assert dropped == {"duplicate_question": 1, "duplicate_sql": 1}


def test_same_result_as_test_matches_on_database_and_result() -> None:
    tests = [{"db_id": "db", "gold_result_hash": "r1"}]
    rows = [_row("a", "q", "s", h="r1"), _row("b", "q", "s", db="x", h="r1")]
    assert same_result_as_test(rows, tests) == {"a"}


def test_finalize_filters_leakage_and_caps_each_database() -> None:
    def rec(q: str, sql: str, h: str, db: str = "db") -> dict:
        return {"db_id": db, "question": q, "sql": sql, "result_hash": h,
                "difficulty": "easy", "decision": "agreed"}  # fmt: skip

    tests = [
        {"id": "t1", "db_id": "db", "question": "How many singers are there?",
         "gold_sql": "SELECT count(*) FROM singer;", "gold_result_hash": "g"},
    ]  # fmt: skip
    records = [
        rec("How many singers are there?", "SELECT 1;", "a"),  # text leak
        rec("Total number of singers?", "SELECT 2;", "g"),  # same result as t1
        rec("Oldest singer name?", "SELECT 3;", "b"),
        rec("Youngest singer name?", "SELECT 4;", "c"),  # over the cap of 1
        {"db_id": "db", "question": "x", "decision": "no_agreement"},
    ]
    kept, drops = finalize(records, tests, n=1)
    assert [r["question"] for r in kept] == ["Oldest singer name?"]
    assert drops["db"] == {
        "test_leakage_text": 1,
        "test_leakage_same_result": 1,
        "over_target": 1,
    }
    rows = to_train_rows(kept, {"db": "CREATE TABLE singer (name VARCHAR);"})
    assert rows[0]["id"] == "synth_db_0001"
    assert rows[0]["source"] == "synthetic"
    assert set(rows[0]) == {
        "id", "db_id", "schema_text", "question", "sql", "source", "difficulty"
    }  # fmt: skip


def test_data_notes_lists_counts_ranges_and_nulls() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (year BIGINT, d DATE, v DOUBLE)")
    con.execute("INSERT INTO t VALUES (2001, '2020-01-02', 1), (2003, NULL, NULL)")
    assert data_notes(con) == (
        "Row counts: t 2.\n"
        "Ranges: t.year 2001 to 2003; t.d 2020-01-02 to 2020-01-02.\n"
        "NULLs: t.d (1 of 2), t.v (1 of 2)."
    )


def test_unordered_limit_flags_limit_without_order_by() -> None:
    assert unordered_limit("SELECT a FROM t LIMIT 5;")
    assert not unordered_limit("SELECT a FROM t ORDER BY a LIMIT 5;")
    assert not unordered_limit("SELECT a FROM (SELECT a FROM t LIMIT 5) ORDER BY a;")
    assert not unordered_limit("SELECT count(*) FROM t;")
