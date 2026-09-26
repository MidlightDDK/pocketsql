import json
from pathlib import Path

import pytest

from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx import own_test, score
from pocketsql.evalx.postprocess import clean_sql
from pocketsql.evalx.sets import load_schemas, load_set


@pytest.mark.parametrize(
    ("raw", "sql"),
    [
        ("SELECT 1", "SELECT 1;"),
        ("  SELECT 1;\nSELECT 2;", "SELECT 1;"),
        ("```sql\nSELECT a FROM t;\n```\nThis query…", "SELECT a FROM t;"),
        ("<think>\nhmm; ok\n</think>\n\nSELECT 'a;b' FROM t", "SELECT 'a;b' FROM t;"),
        ('SELECT "x;y" -- c; d\nFROM t;', 'SELECT "x;y" -- c; d\nFROM t;'),
        ("", ""),
    ],
)
def test_clean_sql(raw: str, sql: str) -> None:
    assert clean_sql(raw) == sql


def test_own_test_items_check_out() -> None:
    items = read_jsonl(own_test.FILES[0])
    assert len(items) == 100
    assert {i["db_id"] for i in items} == {"chinook", "penguins", "world_bank"}
    assert own_test.check(items) == {}


def test_sets_are_fixed() -> None:
    dev = load_set("spider_dev_100")
    assert len(dev) == 100 and dev == load_set("spider_dev_100")
    assert len(load_set("parity")) == 20
    assert {i["db_id"] for i in load_set("own_test")} <= set(load_schemas())


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
