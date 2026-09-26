"""Synthetic question → DuckDB SQL pairs for the demo schemas (M3).

`uv run --project training python -m pocketsql.synth --n 200` (needs GROQ_API_KEY).
Per schema, in rounds over TOPICS:
1. gpt-oss-120b writes a batch of difficulty-tagged questions on a topic, with SQL.
2. gpt-oss-20b and qwen3.8-27b answer the same questions independently, schema only.
3. A question is kept when at least 2 of the 3 SQL candidates return the same result,
   and that result is non-empty and deterministic (own_test's checks). The shortest
   agreeing SQL becomes the target.
Then dedupe, drop test leakage, and keep the first --n per schema. Writes
processed/synth.jsonl (merged into train.jsonl), processed/synth_candidates.jsonl
(every candidate and decision), processed/synth_review.jsonl (50 random kept pairs
for review), and cards/synth_stats.json. All three generators are Apache-2.0.
"""

import argparse
import json
import random
from collections import Counter, defaultdict
from typing import NamedTuple

import duckdb

from pocketsql.data import paths
from pocketsql.data.convert import quote_ident
from pocketsql.data.leakage import find_leaks, read_jsonl
from pocketsql.data.prepare import write_jsonl
from pocketsql.evalx.compare import has_order_by
from pocketsql.evalx.own_test import check_item, reversed_copy
from pocketsql.evalx.sets import DEMO_DBS, db_path, load_schemas
from pocketsql.synth.filters import (
    dedupe,
    one_line,
    plain_text,
    same_result_as_test,
    unordered_limit,
    vote,
)
from pocketsql.synth.llm import Groq, QuotaExhausted, json_content


class Topic(NamedTuple):
    name: str
    focus: str
    joins: bool = False  # needs more than one table


TOPICS = (
    Topic("filters", "filters (=, <, BETWEEN, IN, ILIKE, IS NULL) and top-N lists"),
    Topic("aggregates", "COUNT, SUM, AVG, MIN, MAX, COUNT(DISTINCT), rounding"),
    Topic("grouping", "GROUP BY with HAVING, and ranking groups by an aggregate"),
    Topic("joins", "joins across two to four tables", joins=True),
    Topic("subqueries", "subqueries: IN / NOT IN, EXISTS, comparisons with an average"),
    Topic("windows", "window functions: RANK, running totals, LAG/LEAD, QUALIFY"),
    Topic("time", "dates and periods: years, months, date_trunc, period-over-period"),
    Topic("conditional", "CASE WHEN buckets, percentages, counts with FILTER (WHERE)"),
    Topic("multistep", "multi-step questions with CTEs (WITH), top-N per group"),
    Topic("sets", "UNION / INTERSECT / EXCEPT, and things with no match"),
    Topic("text", "string functions (length, lower, substring, concat), COALESCE"),
)

DIFFICULTIES = ("easy", "medium", "hard", "extra")
JSON_OBJECT = {"type": "json_object"}
GENERATOR = {
    "model": "openai/gpt-oss-120b",
    "temperature": 1.0,
    "reasoning_effort": "low",
    "max_completion_tokens": 8192,
    "response_format": JSON_OBJECT,
}
ANSWERERS = {
    "gpt-oss-20b": {
        "model": "openai/gpt-oss-20b",
        "temperature": 0,
        "reasoning_effort": "low",
        "max_completion_tokens": 4096,
        "response_format": JSON_OBJECT,
    },
    "qwen3.8-27b": {
        "model": "qwen/qwen3.8-27b",
        "temperature": 0,
        "max_completion_tokens": 1000,  # its free-tier ceiling (see llm.py)
        "response_format": JSON_OBJECT,
    },
}
GEN_NAME = "gpt-oss-120b"
BATCH = 20
ANSWER_BATCH = {"gpt-oss-20b": BATCH, "qwen3.8-27b": 7}  # questions per call
AVOID = 30  # earlier questions on the same topic shown to the generator
REVIEW_N = 50
REVIEW_SEED = "pocketsql-synth-review-v1"

SYNTH = paths.SYNTH
CANDIDATES = paths.PROCESSED / "synth_candidates.jsonl"
REVIEW = paths.PROCESSED / "synth_review.jsonl"
STATS = paths.CARDS / "synth_stats.json"

GEN_SYSTEM = (
    "You write training data for a small model that turns questions into DuckDB SQL."
)
GEN_PROMPT = """Database schema:
{schema}

About the data:
{notes}

Write {k} new questions a data analyst might ask about this database, focusing on
{focus}. Give each one the DuckDB SQL query that answers it.

Rules:
- The question must fully determine the answer: say which columns to return, and the
  sort order and row limit when they matter. Avoid ties at a row limit.
- The SQL returns exactly those columns, in the order the question names them. Use
  ORDER BY only when the question asks for an order or a top/bottom N.
- The answer must be non-empty: use values that exist (for example the values in the
  schema comments).
- Prefer answers that are one value or a short table (at most about 20 rows); don't
  list every row of a large table.
- Plain English: don't mention SQL, its keywords, or its functions, and write column
  names as natural words ("bill length", not "bill_length_mm").
- Mix difficulties and tag each one: easy (one table, a simple filter or aggregate),
  medium (grouping, a join, or a top-N), hard (several joins, subqueries, or window
  functions), extra (multi-step logic).
- SQL: one DuckDB statement ending with ";", using only the tables and columns above.
  Round only when the question says so.{avoid}

Return only JSON: {{"items": [{{"question": "…", "difficulty": "…", "sql": "…"}}]}}
(difficulty is one of easy, medium, hard, extra)"""
ANSWER_SYSTEM = "You write DuckDB SQL."
ANSWER_PROMPT = """Database schema:
{schema}

Write one DuckDB SQL query for each question below, ending with ";". Return exactly
the columns the question asks for, in the order it names them. Use ORDER BY only when
the question asks for an order or a top/bottom N.

Questions:
{questions}

Return only JSON: {{"answers": [{{"n": 1, "sql": "..."}}]}}"""


def data_notes(con: duckdb.DuckDBPyConnection) -> str:
    """Row counts, date/year ranges, and columns with NULLs, for the generator only."""
    cols = con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
    ).fetchall()
    counts, ranges, nulls = [], [], []
    for table in dict.fromkeys(t for t, _, _ in cols):
        t = quote_ident(table)
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        counts.append(f"{table} {n}")
        for _, col, dtype in (c for c in cols if c[0] == table):
            c = quote_ident(col)
            lo, hi, present = con.execute(
                f"SELECT min({c}), max({c}), count({c}) FROM {t}"
            ).fetchone()
            if dtype in ("DATE", "TIMESTAMP") or col.lower() == "year":
                ranges.append(f"{table}.{col} {str(lo)[:10]} to {str(hi)[:10]}")
            if present < n:
                nulls.append(f"{table}.{col} ({n - present} of {n})")
    lines = [f"Row counts: {', '.join(counts)}."]
    if ranges:
        lines.append(f"Ranges: {'; '.join(ranges)}.")
    if nulls:
        lines.append(f"NULLs: {', '.join(nulls)}.")
    return "\n".join(lines)


def generate(
    groq: Groq, schema: str, notes: str, topic: Topic, previous: list[str]
) -> list[dict]:
    avoid = ""
    if previous:
        listed = "\n".join(f"  - {q}" for q in previous[-AVOID:])
        avoid = f"\n- Don't repeat these existing questions:\n{listed}"
    prompt = GEN_PROMPT.format(
        schema=schema, notes=notes, k=BATCH, focus=topic.focus, avoid=avoid
    )
    body = {
        **GENERATOR,
        "messages": [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    data = json_content(groq.chat(body)) or {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return [i for i in items if isinstance(i, dict)]


def answer(groq: Groq, name: str, schema: str, questions: list[str]) -> list[str]:
    size = ANSWER_BATCH[name]
    return [
        sql
        for i in range(0, len(questions), size)
        for sql in answer_chunk(groq, name, schema, questions[i : i + size])
    ]


def answer_chunk(groq: Groq, name: str, schema: str, questions: list[str]) -> list[str]:
    listed = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
    body = {
        **ANSWERERS[name],
        "messages": [
            {"role": "system", "content": ANSWER_SYSTEM},
            {
                "role": "user",
                "content": ANSWER_PROMPT.format(schema=schema, questions=listed),
            },
        ],
    }
    data = json_content(groq.chat(body)) or {}
    out = [""] * len(questions)
    for a in data.get("answers") or []:
        if isinstance(a, dict) and isinstance(a.get("n"), int):
            if 1 <= a["n"] <= len(questions) and isinstance(a.get("sql"), str):
                out[a["n"] - 1] = a["sql"]
    return out


def problem_key(problem: str) -> str:
    for prefix, key in (
        ("error", "error"),
        ("empty", "empty"),
        ("all-NULL", "all_null"),
        ("non-deterministic", "nondeterministic"),
        ("ORDER BY ties", "order_ties"),
        ("limit_without_order", "limit_without_order"),
    ):
        if problem.startswith(prefix):
            return key
    return "other"


def evaluate(
    sql_text: str, con: duckdb.DuckDBPyConnection, rev: duckdb.DuckDBPyConnection
) -> dict:
    sql = one_line(sql_text) if sql_text else ""
    if not sql:
        return {"sql": "", "problem": "missing", "hash": None, "ordered": None}
    try:
        problem, h = check_item({"gold_sql": sql}, con, rev)
        ordered = has_order_by(sql)
        if not problem and unordered_limit(sql):
            # Deterministic here only because fewer rows match than the limit.
            problem, h = "limit_without_order", None
    except Exception as e:  # sqlglot parse errors, errors in the tie-break rerun
        problem, h, ordered = f"error: {type(e).__name__}", None, None
    problem = problem and problem_key(problem)
    return {"sql": sql, "problem": problem, "hash": h, "ordered": ordered}


def run_batch(
    groq: Groq,
    db_id: str,
    schema: str,
    items: list[dict],
    con: duckdb.DuckDBPyConnection,
    rev: duckdb.DuckDBPyConnection,
) -> list[dict]:
    questions = [plain_text(str(i.get("question", ""))) for i in items]
    answers = {name: answer(groq, name, schema, questions) for name in ANSWERERS}
    records = []
    for k, (item, question) in enumerate(zip(items, questions, strict=True)):
        difficulty = item.get("difficulty")
        rec = {"db_id": db_id, "question": question, "difficulty": difficulty}
        cands = [(GEN_NAME, str(item.get("sql") or ""))]
        cands += [(name, answers[name][k]) for name in ANSWERERS]
        rec["candidates"] = [{"model": m, **evaluate(s, con, rev)} for m, s in cands]
        if not question or difficulty not in DIFFICULTIES:
            rec["decision"] = "bad_item"
        else:
            # Agreeing means the same result and the same ORDER BY presence: a sorted
            # result hashes like the unsorted one, and a requested order must stay.
            sql, votes = vote(
                [
                    (c["sql"], c["hash"] and f"{c['ordered']}:{c['hash']}")
                    for c in rec["candidates"]
                ]
            )
            valid = sum(1 for c in rec["candidates"] if c["hash"])
            rec["votes"] = votes
            if sql:
                h = next(c["hash"] for c in rec["candidates"] if c["sql"] == sql)
                rec.update(decision="agreed", sql=sql, result_hash=h)
            else:
                rec["decision"] = "no_agreement" if valid >= 2 else "too_few_valid"
        records.append(rec)
    return records


def finalize(
    records: list[dict], tests: list[dict], n: int
) -> tuple[list[dict], dict[str, Counter[str]]]:
    """Agreed records → deduped, leakage-free rows, the first n per database."""
    drops: dict[str, Counter[str]] = defaultdict(Counter)
    agreed = [
        {"id": f"cand_{i:05d}", **r}
        for i, r in enumerate(records)
        if r["decision"] == "agreed"
    ]
    rows = []
    for db in dict.fromkeys(r["db_id"] for r in agreed):
        kept, dropped = dedupe([r for r in agreed if r["db_id"] == db])
        rows += kept
        drops[db].update(dropped)
    leaks = {line.split()[0] for line in find_leaks(rows, tests)}
    same = same_result_as_test(rows, tests) - leaks
    out, per_db = [], Counter()
    for r in rows:
        if r["id"] in leaks:
            drops[r["db_id"]]["test_leakage_text"] += 1
        elif r["id"] in same:
            drops[r["db_id"]]["test_leakage_same_result"] += 1
        elif per_db[r["db_id"]] >= n:
            drops[r["db_id"]]["over_target"] += 1
        else:
            per_db[r["db_id"]] += 1
            out.append(r)
    return out, drops


def to_train_rows(rows: list[dict], schemas: dict[str, str]) -> list[dict]:
    out, seq = [], Counter()
    for r in rows:
        seq[r["db_id"]] += 1
        out.append(
            {
                "id": f"synth_{r['db_id']}_{seq[r['db_id']]:04d}",
                "db_id": r["db_id"],
                "schema_text": schemas[r["db_id"]],
                "question": r["question"],
                "sql": r["sql"],
                "source": "synthetic",
                "difficulty": r["difficulty"],
            }
        )
    return out


def review_sample(rows: list[dict]) -> list[dict]:
    """REVIEW_N random rows, split evenly over DEMO_DBS (17/17/16), seeded per
    database so one schema's sample doesn't depend on the others."""
    sample = []
    for i, db in enumerate(DEMO_DBS):
        k = REVIEW_N // len(DEMO_DBS) + (i < REVIEW_N % len(DEMO_DBS))
        pool = [r for r in rows if r["db_id"] == db]
        sample += random.Random(f"{REVIEW_SEED}:{db}").sample(pool, min(k, len(pool)))
    return sorted(sample, key=lambda r: r["id"])


def merge_into_train(synth: list[dict]) -> int:
    train_path = paths.PROCESSED / "train.jsonl"
    train = [r for r in read_jsonl(train_path) if r["source"] != "synthetic"]
    write_jsonl(train_path, train + synth)
    return len(train) + len(synth)


def stats(records: list[dict], kept: list[dict], drops: dict, groq: Groq) -> dict:
    per_db = {}
    for db in sorted({r["db_id"] for r in records}):
        recs = [r for r in records if r["db_id"] == db]
        rows = [r for r in kept if r["db_id"] == db]
        agreed = [r for r in recs if r["decision"] == "agreed"]
        per_db[db] = {
            "questions": len(recs),
            "decisions": dict(Counter(r["decision"] for r in recs)),
            "votes_of_agreed": dict(Counter(r["votes"] for r in agreed)),
            "dropped_after_agreement": dict(drops.get(db, {})),
            "kept": len(rows),
            "kept_rate": round(len(rows) / len(recs), 4) if recs else 0,
            "difficulty": {
                d: sum(r["difficulty"] == d for r in rows) for d in DIFFICULTIES
            },
        }
    models = [GEN_NAME, *ANSWERERS]
    cands = [c for r in records for c in r["candidates"]]
    per_model = {
        m: {
            "candidates": sum(c["model"] == m for c in cands),
            "valid": sum(c["model"] == m and bool(c["hash"]) for c in cands),
            "problems": dict(
                Counter(c["problem"] for c in cands if c["model"] == m and c["problem"])
            ),
        }
        for m in models
    }
    return {
        "generator": {
            "questions": GENERATOR,
            "answers": ANSWERERS,
            "batch": BATCH,
            "answer_batch": ANSWER_BATCH,
        },
        "topics": [t.name for t in TOPICS],
        "totals": {
            "questions": len(records),
            "agreed": sum(r["decision"] == "agreed" for r in records),
            "dropped_after_agreement": dict(sum(drops.values(), Counter())),
            "kept": len(kept),
        },
        "per_db": per_db,
        "candidates": per_model,
        "groq_usage": {
            m: {"calls": groq.calls[m], "tokens": groq.tokens[m]} for m in groq.calls
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.synth")
    parser.add_argument("--n", type=int, default=200, help="pairs per schema")
    parser.add_argument("--rounds", type=int, default=4, help="max rounds per schema")
    parser.add_argument("--dbs", nargs="+", default=list(DEMO_DBS), choices=DEMO_DBS)
    parser.add_argument("--topics", nargs="+", choices=[t.name for t in TOPICS])
    parser.add_argument("--dry-run", action="store_true", help="print stats only")
    args = parser.parse_args(argv)

    schemas = load_schemas()
    tests = [t for f in sorted(paths.EVAL_SETS.glob("*.jsonl")) for t in read_jsonl(f)]
    groq = Groq()
    records: list[dict] = []
    try:
        for db_id in args.dbs:
            schema = schemas[db_id]
            with (
                duckdb.connect(str(db_path(db_id)), read_only=True) as con,
                reversed_copy(db_id) as rev,
            ):
                notes = data_notes(con)
                multi = (
                    con.execute(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'main'"
                    ).fetchone()[0]
                    > 1
                )
                topics = [
                    t
                    for t in TOPICS
                    if (multi or not t.joins)
                    and (not args.topics or t.name in args.topics)
                ]
                previous: dict[str, list[str]] = defaultdict(list)
                for rnd in range(args.rounds):
                    for topic in topics:
                        items = generate(
                            groq, schema, notes, topic, previous[topic.name]
                        )
                        for rec in run_batch(groq, db_id, schema, items, con, rev):
                            records.append({**rec, "topic": topic.name, "round": rnd})
                        previous[topic.name] += [str(i.get("question")) for i in items]
                    kept, _ = finalize(records, tests, args.n)
                    have = sum(r["db_id"] == db_id for r in kept)
                    print(f"{db_id} round {rnd + 1}: {have} kept", flush=True)
                    if have >= args.n:
                        break
    except QuotaExhausted as e:
        print(f"daily Groq quota spent ({e}); rerun later, cached calls are reused")
        return 2

    kept, drops = finalize(records, tests, args.n)
    report = stats(records, kept, drops, groq)
    print(json.dumps(report["totals"]), json.dumps(report["groq_usage"]))
    for db, s in report["per_db"].items():
        print(db, json.dumps({k: s[k] for k in ("questions", "decisions", "kept")}))
    if args.dry_run:
        return 0
    rows = to_train_rows(kept, schemas)
    write_jsonl(SYNTH, rows)
    write_jsonl(CANDIDATES, records)
    write_jsonl(REVIEW, review_sample(rows))
    STATS.write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    total = merge_into_train(rows)
    print(f"wrote {len(rows)} pairs to {SYNTH.name}; train.jsonl now has {total} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
