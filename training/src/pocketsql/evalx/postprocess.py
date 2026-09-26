"""Turn raw model output into one SQL statement (the same for every runtime)."""

import re

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\n?(.*?)(?:```|$)", re.S)


def first_statement(sql: str) -> str:
    """Everything up to the first `;` outside quotes and comments."""
    quote, i = "", 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
            continue
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        elif ch == ";":
            return sql[:i]
        i += 1
    return sql


def clean_sql(text: str) -> str:
    """Drop thinking blocks and code fences; keep the first statement, ending in `;`."""
    text = _THINK.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    fence = _FENCE.search(text)
    if fence:
        text = fence.group(1)
    sql = first_statement(text).strip()
    return f"{sql};" if sql else ""
