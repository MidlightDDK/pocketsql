"""Eval sets, their databases, and the schema text every runtime prompts with.

`python -m pocketsql.evalx.sets --write-schemas` regenerates evals/sets/schemas.json
(the serialized schema per db_id), so PyTorch, Groq, and Node build identical prompts.
`--write-val` resamples evals/parity/val_50.jsonl from the pinned Hub val split.
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
    # 50 seeded val prompts for artifact parity: shipped ONNX vs merged PyTorch (M5).
    # Not a test set, so it lives outside evals/sets (which the leakage check reads).
    "val_50": paths.EVAL_SETS.parent / "parity" / "val_50.jsonl",
}
VAL_SEED = "pocketsql-val50-v1"
# Fixed Spider-dev samples: 100 for the zero-shot comparison (M2), 200 for the CPU
# artifact eval in CI (M5). Same seed, so spider_dev_100 is a subset of spider_dev_200.
SUBSET_SEED = "pocketsql-dev100-v1"
SUBSETS = {"spider_dev_100": ("spider_dev", 100), "spider_dev_200": ("spider_dev", 200)}
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


def sample_val(n: int = 50) -> list[dict]:
    """Seeded val items whose gold result is stable (non-empty, no ORDER BY ties)."""
    from pocketsql.data.leakage import _hub_files
    from pocketsql.evalx.own_test import check_item, reversed_copy

    key = lambda row: hashlib.sha256(f"{VAL_SEED}:{row['id']}".encode()).digest()  # noqa: E731
    out: list[dict] = []
    for row in sorted(read_jsonl(_hub_files()[1]), key=key):
        item = {
            "id": row["id"],
            "db_id": row["db_id"],
            "question": row["question"],
            "gold_sql": row["sql"],
            "gold_result_hash": "",
            "difficulty": row["difficulty"],
        }
        with (
            duckdb.connect(str(db_path(row["db_id"])), read_only=True) as con,
            reversed_copy(row["db_id"]) as rev,
        ):
            problem, h = check_item(item, con, rev)
        if problem is None and h:
            out.append({**item, "gold_result_hash": h})
        if len(out) == n:
            break
    return sorted(out, key=lambda i: i["id"])


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
    parser.add_argument("--write-val", action="store_true")
    args = parser.parse_args(argv)
    if args.write_val:
        FILES["val_50"].write_text(
            "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in sample_val()),
            encoding="utf-8",
            newline="\n",
        )
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
