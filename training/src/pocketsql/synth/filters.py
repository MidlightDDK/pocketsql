"""Filters for synthetic pairs: SQL cleanup, self-consistency vote, dedupe, leakage."""

import re
from collections import Counter

import sqlglot
from sqlglot import exp

from pocketsql.data.leakage import JACCARD, jaccard, normalize_question, normalize_sql
from pocketsql.evalx.postprocess import clean_sql

_TOKEN = re.compile(
    r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/|\s+|[^\s'\"]+|.", re.S
)


_PUNCT = str.maketrans(
    {
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2212", "-"),
        **dict.fromkeys("\u2018\u2019", "'"),
        **dict.fromkeys("\u201c\u201d", '"'),
        **dict.fromkeys("\u00a0\u202f\u2009", " "),
    }
)


def plain_text(text: str) -> str:
    """ASCII hyphens, quotes, and spaces instead of their typographic variants."""
    return " ".join(text.translate(_PUNCT).split())


def one_line(text: str) -> str:
    """The first statement on one line: comments dropped, whitespace outside quotes
    collapsed, ending in `;` (the target format of every training pair)."""
    sql = clean_sql(text)
    parts: list[str] = []
    for tok in _TOKEN.findall(sql):
        if tok.startswith(("--", "/*")) or tok.isspace():
            if parts and parts[-1] != " ":
                parts.append(" ")
        else:
            parts.append(tok)
    out = "".join(parts).strip()
    out = re.sub(r" ;$", ";", out)
    return out if out != ";" else ""


def unordered_limit(sql: str) -> bool:
    """True when the outer query has LIMIT but no ORDER BY (an arbitrary subset)."""
    tree = sqlglot.parse_one(sql, read="duckdb")
    return (
        isinstance(tree, exp.Query)
        and tree.args.get("limit") is not None
        and tree.args.get("order") is None
    )


def vote(candidates: list[tuple[str, str | None]]) -> tuple[str | None, int]:
    """Pick the SQL for a question from (sql, result hash or None) candidates.

    Returns (sql, votes): the shortest SQL in the largest group of candidates with the
    same result, or (None, votes) when fewer than 2 candidates agree.
    """
    counts = Counter(h for _, h in candidates if h)
    if not counts:
        return None, 0
    best, n = counts.most_common(1)[0]
    if n < 2:
        return None, n
    return min((s for s, h in candidates if h == best), key=len), n


def dedupe(rows: list[dict]) -> tuple[list[dict], Counter[str]]:
    """Drop repeated questions or SQL, and near-duplicate questions (same database)."""
    kept: list[dict] = []
    seen_q: set[tuple[str, str]] = set()
    seen_sql: set[tuple[str, str]] = set()
    tokens: dict[str, list[set[str]]] = {}
    dropped: Counter[str] = Counter()
    for r in rows:
        q, sql = normalize_question(r["question"]), normalize_sql(r["sql"])
        toks = set(q.split())
        if (r["db_id"], q) in seen_q:
            dropped["duplicate_question"] += 1
        elif (r["db_id"], sql) in seen_sql:
            dropped["duplicate_sql"] += 1
        elif any(jaccard(toks, t) >= JACCARD for t in tokens.get(r["db_id"], [])):
            dropped["near_duplicate_question"] += 1
        else:
            seen_q.add((r["db_id"], q))
            seen_sql.add((r["db_id"], sql))
            tokens.setdefault(r["db_id"], []).append(toks)
            kept.append(r)
    return kept, dropped


def same_result_as_test(rows: list[dict], tests: list[dict]) -> set[str]:
    """Ids of rows whose result equals a test item's gold result on the same database:
    a paraphrase of a test question that the text match misses."""
    gold = {
        (t["db_id"], t["gold_result_hash"]) for t in tests if t.get("gold_result_hash")
    }
    return {r["id"] for r in rows if (r["db_id"], r["result_hash"]) in gold}
