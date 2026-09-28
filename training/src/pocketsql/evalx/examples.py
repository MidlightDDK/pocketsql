"""Precomputed web examples from the released artifact's own_test predictions.

`python -m pocketsql.evalx.examples` writes web/src/data/examples.json (6 questions
the shipped q4f16 model answered correctly, with their result rows, shown instantly
while the model downloads) and web/src/data/failures.json (one real failure per
error tag, for the /evals page).
"""

import datetime as dt
import decimal
import json
from pathlib import Path

from pocketsql.data import paths
from pocketsql.evalx.compare import has_order_by
from pocketsql.evalx.score import connect, score_file
from pocketsql.evalx.sets import load_set

PREDICTIONS = (
    paths.REPO
    / "evals"
    / "predictions"
    / "pocketsql-0.5b-v2__onnx-q4f16-webgpu__own_test.jsonl"
)
OUT = paths.REPO / "web" / "src" / "data"
# Two per demo dataset, chosen for shapes the app can chart or show at a glance.
EXAMPLE_IDS = (
    "own_chinook_16",
    "own_chinook_18",
    "own_penguins_10",
    "own_penguins_16",
    "own_world_bank_10",
    "own_world_bank_18",
)
MAX_ROWS = 100


def _cell(v: object) -> object:
    if isinstance(v, decimal.Decimal | float):
        return round(float(v), 6)
    if isinstance(v, dt.date | dt.datetime | dt.time | dt.timedelta):
        return str(v)
    return v


def build() -> tuple[list[dict], list[dict]]:
    _, outcomes = score_file(PREDICTIONS)
    by_id = {o["id"]: o for o in outcomes}
    items = {i["id"]: i for i in load_set("own_test")}
    examples = []
    for id_ in EXAMPLE_IDS:
        item, outcome = items[id_], by_id[id_]
        if not outcome["ex"]:
            raise SystemExit(f"{id_}: the released model got it wrong; pick another")
        with connect(item["db_id"]) as con:
            cur = con.execute(outcome["sql"])
            columns = [d[0] for d in cur.description]
            rows = [[_cell(v) for v in r] for r in cur.fetchmany(MAX_ROWS)]
        # Without ORDER BY, DuckDB's row order varies from run to run.
        if not has_order_by(outcome["sql"]):
            rows.sort(key=lambda r: [str(v) for v in r])
        examples.append(
            {
                "id": id_,
                "db_id": item["db_id"],
                "question": item["question"],
                "sql": outcome["sql"],
                "columns": columns,
                "rows": rows,
            }
        )
    failures, seen = [], set()
    for o in outcomes:
        if o["ex"] or o["tag"] in seen:
            continue
        seen.add(o["tag"])
        item = items[o["id"]]
        failures.append(
            {
                "id": o["id"],
                "db_id": item["db_id"],
                "difficulty": item["difficulty"],
                "question": item["question"],
                "tag": o["tag"],
                "sql": o["sql"],
                "gold_sql": item["gold_sql"],
                "error": o["error"],
            }
        )
    return examples, failures


def _write(path: Path, data: list[dict]) -> None:
    path.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    examples, failures = build()
    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "examples.json", examples)
    _write(OUT / "failures.json", failures)
    print(f"wrote {len(examples)} examples, {len(failures)} failure examples to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
