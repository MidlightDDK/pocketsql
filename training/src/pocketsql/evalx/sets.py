"""Eval sets, their databases, and the schema text every runtime prompts with.

`python -m pocketsql.evalx.sets --write-schemas` regenerates evals/sets/schemas.json
(the serialized schema per db_id), so PyTorch, Groq, and Node build identical prompts.
"""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.data.schema import introspect, serialize

DEMO_DBS = ("chinook", "penguins", "world_bank")
SCHEMAS = paths.EVAL_SETS / "schemas.json"
FILES = {
    "own_test": paths.EVAL_SETS / "own_test.jsonl",
    "spider_dev": paths.EVAL_SETS / "spider_dev_duckdb.jsonl",
}
# A fixed 100-item Spider-dev sample for the zero-shot comparison (M2).
SUBSET_SEED = "pocketsql-dev100-v1"
SUBSETS = {"spider_dev_100": ("spider_dev", 100)}
# 20 fixture prompts for export parity (ONNX vs PyTorch greedy output): every 10th item.
PARITY = ("own_test", "spider_dev_100")
SET_NAMES = (*FILES, *SUBSETS, "parity")


def db_path(db_id: str) -> Path:
    if db_id in DEMO_DBS:
        return paths.DEMO_DIR / f"{db_id}.duckdb"
    return paths.DUCKDB_DIR / f"{db_id}.duckdb"


def load_set(name: str) -> list[dict]:
    if name in FILES:
        return read_jsonl(FILES[name])
    if name == "parity":
        return [i for base in PARITY for i in load_set(base)[::10]]
    base, n = SUBSETS[name]
    key = lambda item: hashlib.sha256(f"{SUBSET_SEED}:{item['id']}".encode()).digest()  # noqa: E731
    return sorted(sorted(load_set(base), key=key)[:n], key=lambda item: item["id"])


def schema_text(con: duckdb.DuckDBPyConnection) -> str:
    return serialize(introspect(con))


def load_schemas() -> dict[str, str]:
    return json.loads(SCHEMAS.read_text(encoding="utf-8"))


def build_schemas() -> dict[str, str]:
    db_ids = sorted({i["db_id"] for f in FILES.values() for i in read_jsonl(f)})
    out = {}
    for db_id in db_ids:
        with duckdb.connect(str(db_path(db_id)), read_only=True) as con:
            out[db_id] = schema_text(con)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.sets")
    parser.add_argument("--write-schemas", action="store_true")
    args = parser.parse_args(argv)
    if args.write_schemas:
        schemas = build_schemas()
        SCHEMAS.write_text(
            json.dumps(schemas, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {len(schemas)} schemas to {SCHEMAS}")
    for name in SET_NAMES:
        print(f"{name}: {len(load_set(name))} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
