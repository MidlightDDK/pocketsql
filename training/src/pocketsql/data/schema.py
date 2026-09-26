"""Schema serializer and prompt builder, mirrored byte-for-byte by
packages/sqlgen/src/schema.ts; both must reproduce
packages/sqlgen/fixtures/golden/*.txt.

Schema JSON: {"tables": [{"name", "columns": [{"name", "type", "examples"?}]}]}.
"""

import re
from typing import NotRequired, TypedDict

import duckdb

from pocketsql.data.convert import quote_ident

SYSTEM_PROMPT = "Write one DuckDB SQL query that answers the question. Output only SQL."

MAX_DISTINCT = 20
MAX_EXAMPLES = 2
MAX_EXAMPLE_CHARS = 40

# DuckDB 1.5.5: SELECT keyword_name FROM duckdb_keywords()
#   WHERE keyword_category = 'reserved'
RESERVED = frozenset(
    "all analyse analyze and any array as asc asymmetric both case cast "
    "check collate column constraint create default deferrable desc "
    "describe distinct do else end except false fetch for foreign from "
    "group having in initially intersect into lambda lateral leading limit "
    "not null offset on only or order pivot pivot_longer pivot_wider "
    "placing primary qualify references returning select show some "
    "summarize symmetric table then to trailing true union unique unpivot "
    "using variadic when where window with".split()
)
_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Column(TypedDict):
    name: str
    type: str
    examples: NotRequired[list[str]]


class Table(TypedDict):
    name: str
    columns: list[Column]


class Schema(TypedDict):
    tables: list[Table]


def ident(name: str) -> str:
    if _PLAIN.fullmatch(name) and name.lower() not in RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


def _column(c: Column) -> str:
    out = f"{ident(c['name'])} {c['type']}"
    examples = c.get("examples") or []
    if examples:
        quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in examples)
        out += f" /* e.g. {quoted} */"
    return out


def serialize(schema: Schema) -> str:
    """One `CREATE TABLE t (col TYPE, …);` line per table."""
    return "\n".join(
        f"CREATE TABLE {ident(t['name'])} ({', '.join(map(_column, t['columns']))});"
        for t in schema["tables"]
    )


def user_prompt(schema_text: str, question: str) -> str:
    return f"{schema_text}\n\nQuestion: {question.strip(' \t\n\r')}"


def messages(schema_text: str, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt(schema_text, question)},
    ]


def _usable_example(v: str) -> bool:
    no_control = all(ord(ch) >= 32 and ord(ch) != 127 for ch in v)
    return 0 < len(v) <= MAX_EXAMPLE_CHARS and no_control and "*/" not in v


def introspect(con: duckdb.DuckDBPyConnection) -> Schema:
    """Read schema `main`: tables sorted case-insensitively, columns in table order.

    Examples: for VARCHAR columns with 1–20 distinct values, the 2 most frequent
    values (ties by value) that are 1–40 chars, without control chars or `*/`.
    """
    names = [
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
        ).fetchall()
    ]
    tables: list[Table] = []
    for t in sorted(names, key=lambda n: (n.lower(), n)):
        cols: list[Column] = []
        for name, typ in con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [t],
        ).fetchall():
            col: Column = {"name": name, "type": typ}
            if typ == "VARCHAR":
                c, qt = quote_ident(name), quote_ident(t)
                (distinct,) = con.execute(
                    f"SELECT count(DISTINCT {c}) FROM {qt}"
                ).fetchone() or (0,)
                if 0 < distinct <= MAX_DISTINCT:
                    values = con.execute(
                        f"SELECT {c} FROM {qt} WHERE {c} IS NOT NULL "
                        f"GROUP BY {c} ORDER BY count(*) DESC, {c}"
                    ).fetchall()
                    examples = [v for (v,) in values if _usable_example(v)]
                    if examples:
                        col["examples"] = examples[:MAX_EXAMPLES]
            cols.append(col)
        tables.append({"name": t, "columns": cols})
    return {"tables": tables}
