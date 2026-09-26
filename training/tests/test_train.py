import ast
import re
import tomllib
from pathlib import Path

import duckdb
import yaml

from pocketsql.data import paths
from pocketsql.data.schema import SYSTEM_PROMPT
from pocketsql.evalx.models import MODELS
from pocketsql.train.evaluate import score
from pocketsql.train.sft import fit_length, to_example

CONFIGS = sorted((paths.REPO / "training" / "configs").glob("train_*.yaml"))
KERNEL = paths.REPO / "kaggle" / "train" / "train.py"


def _row(id_: str, sql: str, schema: str = "CREATE TABLE t (a BIGINT);") -> dict:
    return {
        "id": id_,
        "db_id": "toy",
        "schema_text": schema,
        "question": "q?",
        "sql": sql,
        "difficulty": "easy",
    }


def test_to_example_is_prompt_completion() -> None:
    ex = to_example(_row("x", "SELECT 1;"))
    assert [m["role"] for m in ex["prompt"]] == ["system", "user"]
    assert ex["prompt"][0]["content"] == SYSTEM_PROMPT
    assert ex["completion"] == [{"role": "assistant", "content": "SELECT 1;"}]


class _CharTokenizer:
    def apply_chat_template(self, msgs, **_) -> dict:
        return {"input_ids": list("".join(m["content"] for m in msgs))}


def test_fit_length_drops_long_pairs() -> None:
    short, long = _row("s", "SELECT 1;"), _row("l", "SELECT " + "1+" * 500 + "1;")
    budget = len(
        _CharTokenizer().apply_chat_template(to_example(short)["prompt"])["input_ids"]
    )
    kept, dropped = fit_length(_CharTokenizer(), [short, long], budget + 50)
    assert kept == [short] and dropped == ["l"]


def test_score(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / "toy.duckdb")) as con:
        con.execute("CREATE TABLE t AS SELECT * FROM range(3) r(a)")
    items = [
        _row("ok", "SELECT a FROM t ORDER BY a;"),
        _row("wrong_order", "SELECT a FROM t ORDER BY a;"),
        _row("invalid", "SELECT a FROM t;"),
        _row("missing", "SELECT a FROM t;"),
    ]
    sqls = {
        "ok": "```sql\nSELECT a FROM t ORDER BY a\n```",
        "wrong_order": "SELECT a FROM t ORDER BY a DESC",
        "invalid": "SELECT nope FROM t",
    }
    summary, outcomes = score(items, sqls, tmp_path)
    assert [o["ex"] for o in outcomes] == [True, False, False, False]
    assert summary["ex"] == 0.25 and summary["valid_sql"] == 0.5


def test_config_pins() -> None:
    assert CONFIGS
    for path in CONFIGS:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert path.stem == f"train_{cfg['run_id']}"
        assert cfg["base_model"] in MODELS
        assert re.fullmatch(r"[0-9a-f]{40}", cfg["dataset"]["revision"])


def test_kernel_pins_match_lockfile() -> None:
    lock = tomllib.loads((paths.REPO / "training" / "uv.lock").read_text("utf-8"))
    locked = {p["name"]: p["version"] for p in lock["package"] if "version" in p}
    tree = ast.parse(KERNEL.read_text(encoding="utf-8"))
    pins = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "PINS"
    )
    for pin in pins:
        name, ver = pin.split("==")
        assert locked[name] == ver, pin
