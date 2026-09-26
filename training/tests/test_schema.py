import json

import duckdb
import pytest

from pocketsql.data import paths
from pocketsql.data.schema import ident, introspect, serialize, user_prompt

GOLDEN = sorted((paths.FIXTURES / "golden").glob("*.json"))


def test_golden_count() -> None:
    assert len(GOLDEN) >= 5


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_golden(path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    expected = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert user_prompt(serialize(case["schema"]), case["question"]) == expected


def test_ident() -> None:
    assert ident("singer_id") == "singer_id"
    assert ident("Order") == '"Order"'
    assert ident('x"y') == '"x""y"'


def test_introspect_examples_and_order() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE zeta (a BIGINT)")
    con.execute("CREATE TABLE Alpha (kind VARCHAR, note VARCHAR, many VARCHAR)")
    rows = [("b", "x" * 41, str(i)) for i in range(3)]
    rows += [("a", "ok", str(10 + i)) for i in range(3)]
    rows += [("c", "*/", str(20 + i)) for i in range(18)]
    con.executemany("INSERT INTO Alpha VALUES (?, ?, ?)", rows)
    schema = introspect(con)
    assert [t["name"] for t in schema["tables"]] == ["Alpha", "zeta"]
    kind, note, many = schema["tables"][0]["columns"]
    assert kind["examples"] == ["c", "a"]  # most frequent first, ties by value
    assert note["examples"] == ["ok"]  # too long and "*/" values skipped
    assert "examples" not in many  # 24 distinct values > 20
