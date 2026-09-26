"""Spider → DuckDB pairs: train/val JSONL, the Spider-dev test set, and stats.

Every Spider database becomes a DuckDB file; every gold query is transpiled and kept
only if DuckDB returns the same result as SQLite. Val is a set of held-out Spider
train databases (no database in both train and val); Spider dev is the test set.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb
import sqlglot

from pocketsql.data import paths
from pocketsql.data.convert import hardness, load_sqlite, schema_names, transpile
from pocketsql.data.download import fetch, sha256
from pocketsql.data.leakage import check, normalize_question, normalize_sql
from pocketsql.data.schema import introspect, serialize
from pocketsql.evalx.compare import (
    has_order_by,
    result_hash,
    results_match,
    run_duckdb,
    run_sqlite,
)

VAL_FRACTION = 0.10
VAL_SEED = "pocketsql-val-v1"
TEST_SET = paths.EVAL_SETS / "spider_dev_duckdb.jsonl"


def spider_root() -> Path:
    root = paths.RAW / "spider_data"
    if not (root / "dev.json").exists():
        with zipfile.ZipFile(fetch("spider")) as z:
            z.extractall(paths.RAW)
    return root


def load_items(root: Path) -> list[dict]:
    items = []
    train = [
        (x, "spider_others" if f == "train_others" else "spider")
        for f in ("train_spider", "train_others")
        for x in json.loads((root / f"{f}.json").read_text(encoding="utf-8"))
    ]
    for i, (x, source) in enumerate(train):
        items.append(
            {"id": f"spider_train_{i:05d}", "split": "train", "source": source, **x}
        )
    dev = json.loads((root / "dev.json").read_text(encoding="utf-8"))
    for i, x in enumerate(dev):
        items.append(
            {"id": f"spider_dev_{i:04d}", "split": "dev", "source": "spider", **x}
        )
    return items


def process_db(job: tuple[Path, str, list[dict]]) -> dict:
    root, db_id, items = job
    src = root / "database" / db_id / f"{db_id}.sqlite"
    dest = paths.DUCKDB_DIR / f"{db_id}.duckdb"
    notes = load_sqlite(src, dest)
    con = duckdb.connect(str(dest), read_only=True)
    con.execute("SET threads = 2")
    schema_text = serialize(introspect(con))
    names = schema_names(con)
    kept, dropped = [], Counter()
    for it in items:
        try:
            sql = transpile(it["query"], names)
        except sqlglot.errors.SqlglotError:
            dropped["transpile_error"] += 1
            continue
        try:
            gold = run_sqlite(src, it["query"])
        except sqlite3.Error:
            dropped["sqlite_error"] += 1
            continue
        try:
            got = run_duckdb(con, sql)
        except duckdb.Error:
            dropped["duckdb_error"] += 1
            continue
        ordered = has_order_by(sql)
        if not results_match(gold, got, ordered):
            dropped["result_mismatch"] += 1
            continue
        kept.append(
            {
                "id": it["id"],
                "db_id": db_id,
                "split": it["split"],
                "source": it["source"],
                "question": it["question"].strip(),
                "sql": sql,
                "difficulty": hardness(it["sql"]),
                "result_hash": result_hash(got, ordered),
                "empty": not got,
            }
        )
    con.close()
    return {
        "db_id": db_id,
        "schema_text": schema_text,
        "notes": notes,
        "total": len(items),
        "kept": kept,
        "dropped": dict(dropped),
    }


def pick_val_dbs(kept: list[dict]) -> list[str]:
    per_db = Counter(k["db_id"] for k in kept if k["source"] == "spider")
    order = sorted(
        per_db, key=lambda d: hashlib.sha256(f"{VAL_SEED}:{d}".encode()).hexdigest()
    )
    target = VAL_FRACTION * len(kept)
    val, n = [], 0
    for db in order:
        if n >= target:
            break
        val.append(db)
        n += per_db[db]
    return sorted(val)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _pct(xs: list[int]) -> dict[str, int]:
    xs = sorted(xs)
    return {
        "p50": int(statistics.median(xs)),
        "p95": xs[int(0.95 * (len(xs) - 1))],
        "max": xs[-1],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.data.prepare")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument(
        "--no-tokens", action="store_true", help="skip token-length stats"
    )
    args = parser.parse_args(argv)

    root = spider_root()
    items = load_items(root)
    by_db: dict[str, list[dict]] = {}
    for it in items:
        by_db.setdefault(it["db_id"], []).append(it)
    paths.DUCKDB_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [
        (root, db, its) for db, its in sorted(by_db.items(), key=lambda kv: -len(kv[1]))
    ]
    with ProcessPoolExecutor(args.workers) as pool:
        results = {r["db_id"]: r for r in pool.map(process_db, jobs)}

    schema_text = {db: r["schema_text"] for db, r in results.items()}
    kept = [k for db in sorted(results) for k in results[db]["kept"]]
    train_kept = [k for k in kept if k["split"] == "train"]
    dev_kept = [k for k in kept if k["split"] == "dev"]

    # Drop exact duplicates within train (same database, question, and SQL).
    seen, deduped = set(), []
    for k in sorted(train_kept, key=lambda k: k["id"]):
        key = (k["db_id"], normalize_question(k["question"]), normalize_sql(k["sql"]))
        if key not in seen:
            seen.add(key)
            deduped.append(k)
    duplicates = len(train_kept) - len(deduped)

    val_dbs = set(pick_val_dbs(deduped))
    fields = ("id", "db_id", "question", "sql", "source", "difficulty")

    def row(k: dict) -> dict:
        r = {f: k[f] for f in fields}
        return {
            "id": r["id"],
            "db_id": r["db_id"],
            "schema_text": schema_text[k["db_id"]],
            **r,
        }

    train = [row(k) for k in deduped if k["db_id"] not in val_dbs]
    val = [row(k) for k in deduped if k["db_id"] in val_dbs]
    test = [
        {
            "id": k["id"],
            "db_id": k["db_id"],
            "question": k["question"],
            "gold_sql": k["sql"],
            "gold_result_hash": k["result_hash"],
            "difficulty": k["difficulty"],
        }
        for k in sorted(dev_kept, key=lambda k: k["id"])
    ]
    write_jsonl(paths.PROCESSED / "train.jsonl", train)
    write_jsonl(paths.PROCESSED / "val.jsonl", val)
    write_jsonl(TEST_SET, test)

    # DuckDB files needed to score val and the Spider-dev test set.
    archive = paths.PROCESSED / "databases.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for db in sorted(val_dbs | {t["db_id"] for t in test}):
            z.write(paths.DUCKDB_DIR / f"{db}.duckdb", f"{db}.duckdb")

    problems = check(train, val, test)

    def split_of(db: str) -> str:
        return (
            "dev"
            if by_db[db][0]["split"] == "dev"
            else "val"
            if db in val_dbs
            else "train"
        )

    def totals(split: str) -> dict:
        dbs = [r for db, r in results.items() if split_of(db) == split]
        n, k = sum(r["total"] for r in dbs), sum(len(r["kept"]) for r in dbs)
        dropped = Counter()
        for r in dbs:
            dropped.update(r["dropped"])
        return {
            "databases": len(dbs),
            "pairs": n,
            "kept": k,
            "retention": round(k / n, 4),
            "dropped": dict(sorted(dropped.items())),
        }

    def difficulty(rows: list[dict]) -> dict[str, int]:
        c = Counter(r["difficulty"] for r in rows)
        return {d: c[d] for d in ("easy", "medium", "hard", "extra")}

    stats = {
        "spider_sha256": sha256(fetch("spider")),
        "outputs": {
            "train": len(train),
            "val": len(val),
            "spider_dev_duckdb": len(test),
        },
        "by_split": {s: totals(s) for s in ("train", "val", "dev")},
        "train_duplicates_removed": duplicates,
        "empty_results": {
            "train+val": sum(k["empty"] for k in deduped),
            "spider_dev_duckdb": sum(k["empty"] for k in dev_kept),
        },
        "difficulty": {
            "train": difficulty(train),
            "val": difficulty(val),
            "spider_dev_duckdb": difficulty(test),
        },
        "val_databases": sorted(val_dbs),
        "leakage_problems": len(problems),
        "schema_chars": _pct([len(s) for s in schema_text.values()]),
        "databases": {
            db: {
                "split": split_of(db),
                "pairs": r["total"],
                "kept": len(r["kept"]),
                "retention": round(len(r["kept"]) / r["total"], 4),
                "dropped": r["dropped"],
                "notes": r["notes"],
            }
            for db, r in sorted(results.items())
        },
    }
    if not args.no_tokens:
        from pocketsql.data.tokens import prompt_ids, tokenizer

        tok = tokenizer()
        lengths = [
            len(prompt_ids(r["schema_text"], r["question"]))
            + len(tok.encode(r["sql"]))
            + 2
            for r in train + val
        ]
        stats["train_val_tokens_prompt_plus_sql"] = _pct(lengths)
    paths.CARDS.mkdir(parents=True, exist_ok=True)
    (paths.CARDS / "stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for split in ("train", "val", "dev"):
        t = stats["by_split"][split]
        kept = f"{t['kept']}/{t['pairs']} kept ({t['retention']:.1%})"
        print(f"{split}: {kept} {t['dropped']}")
    print(f"outputs: {stats['outputs']}; duplicates removed: {duplicates}")
    print(f"leakage problems: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
