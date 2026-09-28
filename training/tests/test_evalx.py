import json
from pathlib import Path

import duckdb
import pytest

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx import cascade, own_test, score
from pocketsql.evalx.postprocess import clean_sql
from pocketsql.evalx.sets import load_schemas, load_set


@pytest.mark.parametrize(
    ("raw", "sql"),
    json.loads((paths.FIXTURES / "clean_sql.json").read_text(encoding="utf-8")),
)
def test_clean_sql(raw: str, sql: str) -> None:
    assert clean_sql(raw) == sql


def test_own_test_items_check_out() -> None:
    items = read_jsonl(own_test.FILES[0])
    assert len(items) == 100
    assert {i["db_id"] for i in items} == {"chinook", "penguins", "world_bank"}
    assert own_test.check(items) == {}


def test_tie_broken_appends_every_output_column() -> None:
    sql = "SELECT a, sum(b) AS s FROM t GROUP BY a ORDER BY s DESC LIMIT 5"
    assert own_test.tie_broken(sql, desc=True).endswith(
        "ORDER BY s DESC, 1 DESC, 2 DESC LIMIT 5"
    )
    assert own_test.tie_broken(sql, desc=False).endswith(
        "ORDER BY s DESC, 1 ASC, 2 ASC LIMIT 5"
    )


def test_sets_are_fixed() -> None:
    dev = load_set("spider_dev_100")
    assert len(dev) == 100 and dev == load_set("spider_dev_100")
    assert len(load_set("parity")) == 20
    dev200 = {i["id"] for i in load_set("spider_dev_200")}
    assert len(dev200) == 200 and {i["id"] for i in dev} <= dev200
    val = load_set("val_50")
    assert len(val) == 50 and all(i["id"].startswith("spider_train_") for i in val)
    for name in ("own_test", "val_50", "spider_dev"):
        assert {i["db_id"] for i in load_set(name)} <= set(load_schemas())


def test_gold_predictions_score_perfectly(tmp_path: Path) -> None:
    path = tmp_path / "gold__copy__own_test.jsonl"
    rows = [{"id": i["id"], "sql": i["gold_sql"]} for i in load_set("own_test")]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    summary, _ = score.score_file(path)
    assert (summary["ex"], summary["valid_sql"], summary["exact_match"]) == (1, 1, 1)


GOLD = "SELECT a FROM t JOIN s ON s.k = t.k;"


@pytest.mark.parametrize(
    ("sql", "error", "tag"),
    [
        ("Here is the query", None, "formatting"),
        ("SELECT x FROM t;", "Parser Error: syntax error at or near", "dialect error"),
        (
            "SELECT n FROM t;",
            'Binder Error: Referenced column "n" not found',
            "hallucinated schema",
        ),
        ("SELECT a FROM t;", None, "wrong column or table"),
        (
            "SELECT a FROM t JOIN s ON s.k = t.k JOIN s AS u ON u.k = t.k;",
            None,
            "join error",
        ),
        ("SELECT max(a) FROM t JOIN s ON s.k = t.k;", None, "aggregation"),
    ],
)
def test_error_tags(sql: str, error: str | None, tag: str) -> None:
    assert score.error_tag(sql, error, GOLD, None) == tag


def test_cascade_escalation_reasons() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a'), (2, NULL)) v(k, s)")
    ok = "SELECT k FROM t ORDER BY k"
    assert cascade.escalation(con, "SELECT nope FROM t", ok) == "error"
    assert cascade.escalation(con, "SELECT k FROM t WHERE k > 5", ok) == "empty"
    assert cascade.escalation(con, "SELECT s FROM t WHERE k = 2", ok) == "empty"
    assert cascade.escalation(con, ok, "SELECT k FROM t WHERE k = 1") == "disagree"
    assert cascade.escalation(con, ok, "SELECT broken") == "disagree"
    assert cascade.escalation(con, ok, "SELECT k FROM t ORDER BY k DESC") == "disagree"
    assert cascade.escalation(con, ok, "SELECT k FROM t") is None


def test_cascade_summary() -> None:
    def item(reason: str | None, local_ex: bool, big_ex: bool) -> dict:
        return {
            "reason": reason,
            "local_ex": local_ex,
            "big_ex": big_ex,
            "big_cost": 1e-4,
        }

    outcomes = [
        item(None, True, True),
        item("disagree", False, True),
        item("error", False, True),
        item("empty", False, False),
    ]
    valid = cascade.summarize(outcomes, "valid")
    assert (valid["answered_locally"], valid["local_precision"], valid["ex"]) == (
        0.5,
        0.5,
        0.5,
    )
    assert valid["api_calls_per_100"] == 50 and valid["cost_per_query_usd"] == 5e-5
    agree = cascade.summarize(outcomes, "agree")
    assert (agree["answered_locally"], agree["local_precision"], agree["ex"]) == (
        0.25,
        1,
        0.75,
    )
    assert agree["escalations"] == {"error": 1, "empty": 1, "disagree": 1}
    assert (agree["local_ex"], agree["big_ex"]) == (0.25, 0.75)
