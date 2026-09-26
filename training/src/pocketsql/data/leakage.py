"""Leakage check: no train/val item may match a test item (evals/sets/*.jsonl).

A match is a shared database with an identical normalized question or SQL, or a
question token-Jaccard ≥ 0.9. Val must also share no database with train.
Run locally on training/data/processed, or with --from-hub on the pinned dataset.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from pocketsql.data import paths

JACCARD = 0.9
# Pinned dataset revision for CI (bump after every dataset upload).
HUB_REPO = "MidlightDDK/pocketsql-data"
HUB_REVISION = "b078ef1fa000c95020ebd50f093abde126126e4e"


def normalize_question(q: str) -> str:
    return " ".join(re.findall(r"\w+", q.lower()))


def normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().rstrip("; \n").split())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def find_leaks(train: list[dict], tests: list[dict]) -> list[str]:
    by_db: dict[str, list[tuple[str, str, str, set[str]]]] = defaultdict(list)
    for t in tests:
        q = normalize_question(t["question"])
        by_db[t["db_id"]].append(
            (t["id"], q, normalize_sql(t["gold_sql"]), set(q.split()))
        )
    leaks = []
    for item in train:
        q = normalize_question(item["question"])
        sql, toks = normalize_sql(item["sql"]), set(q.split())
        for test_id, tq, tsql, ttoks in by_db.get(item["db_id"], []):
            if q == tq or sql == tsql or jaccard(toks, ttoks) >= JACCARD:
                leaks.append(f"{item['id']} ~ {test_id} ({item['db_id']})")
    return leaks


def check(train: list[dict], val: list[dict], tests: list[dict]) -> list[str]:
    problems = find_leaks(train + val, tests)
    shared = {i["db_id"] for i in train} & {i["db_id"] for i in val}
    problems += [f"database {db} is in both train and val" for db in sorted(shared)]
    return problems


def _hub_files() -> tuple[Path, Path]:
    from huggingface_hub import hf_hub_download

    get = lambda name: Path(  # noqa: E731
        hf_hub_download(HUB_REPO, name, repo_type="dataset", revision=HUB_REVISION)
    )
    return get("train.jsonl"), get("val.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.data.leakage")
    parser.add_argument(
        "--from-hub", action="store_true", help="check the pinned Hub revision"
    )
    args = parser.parse_args(argv)
    if args.from_hub:
        train_path, val_path = _hub_files()
    else:
        train_path, val_path = (
            paths.PROCESSED / "train.jsonl",
            paths.PROCESSED / "val.jsonl",
        )
    train, val = read_jsonl(train_path), read_jsonl(val_path)
    tests = [t for f in sorted(paths.EVAL_SETS.glob("*.jsonl")) for t in read_jsonl(f)]
    problems = check(train, val, tests)
    for p in problems[:50]:
        print(p)
    print(
        f"leakage check: {len(train)} train + {len(val)} val vs {len(tests)} "
        f"test items, {len(problems)} problems"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
