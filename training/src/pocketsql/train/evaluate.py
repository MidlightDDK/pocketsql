"""Val execution accuracy (EX) of a PyTorch model: batched greedy decoding with the
model's generation config (as predict_torch and Transformers.js use it), scored like
pocketsql.evalx.score: clean_sql, then both result sets from DuckDB."""

from collections import Counter
from pathlib import Path

import duckdb

from pocketsql.data.schema import messages
from pocketsql.evalx.compare import has_order_by, results_match, run_duckdb
from pocketsql.evalx.postprocess import clean_sql

TIMEOUT_S = 10.0
DIFFICULTIES = ("easy", "medium", "hard", "extra")


def score(
    items: list[dict], sqls: dict[str, str], db_dir: Path
) -> tuple[dict, list[dict]]:
    """Summary and per-item outcomes of predicted SQL against each item's gold `sql`."""
    by_db: dict[str, list[dict]] = {}
    for item in items:
        by_db.setdefault(item["db_id"], []).append(item)
    outcomes = []
    for db_id, group in sorted(by_db.items()):
        with duckdb.connect(
            str(db_dir / f"{db_id}.duckdb"),
            read_only=True,
            config={"enable_external_access": False},
        ) as con:
            for item in group:
                gold = run_duckdb(con, item["sql"], TIMEOUT_S)
                sql = clean_sql(sqls.get(item["id"], ""))
                try:
                    rows = run_duckdb(con, sql, TIMEOUT_S) if sql else None
                except duckdb.Error:
                    rows = None
                ok = rows is not None and results_match(
                    gold, rows, has_order_by(item["sql"])
                )
                outcomes.append(
                    {
                        "id": item["id"],
                        "difficulty": item["difficulty"],
                        "valid": rows is not None,
                        "ex": ok,
                    }
                )
    n = len(outcomes)
    counts = Counter(o["difficulty"] for o in outcomes)
    summary = {
        "n": n,
        "ex": round(sum(o["ex"] for o in outcomes) / n, 4),
        "valid_sql": round(sum(o["valid"] for o in outcomes) / n, 4),
        "by_difficulty": {
            d: {
                "n": counts[d],
                "ex": round(
                    sum(o["ex"] for o in outcomes if o["difficulty"] == d) / counts[d],
                    4,
                ),
            }
            for d in DIFFICULTIES
            if counts[d]
        },
    }
    return summary, outcomes


def generate(
    model, tok, items: list[dict], batch_size: int, max_new_tokens: int
) -> dict[str, str]:
    """Raw completions by item id; prompts are left-padded, longest first."""
    import torch

    prompts = {
        i["id"]: tok.apply_chat_template(
            messages(i["schema_text"], i["question"]),
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
        )["input_ids"]
        for i in items
    }
    order = sorted(prompts, key=lambda k: -len(prompts[k]))
    out: dict[str, str] = {}
    for start in range(0, len(order), batch_size):
        keys = order[start : start + batch_size]
        width = max(len(prompts[k]) for k in keys)
        ids = torch.full((len(keys), width), tok.pad_token_id, dtype=torch.long)
        mask = torch.zeros_like(ids)
        for row, k in enumerate(keys):
            p = prompts[k]
            ids[row, width - len(p) :] = torch.tensor(p)
            mask[row, width - len(p) :] = 1
        with torch.inference_mode():
            gen = model.generate(
                input_ids=ids.to(model.device),
                attention_mask=mask.to(model.device),
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tok.pad_token_id,
            )
        for row, k in enumerate(keys):
            out[k] = tok.decode(gen[row, width:], skip_special_tokens=True)
        print(
            f"generated {min(start + batch_size, len(order))}/{len(order)}", flush=True
        )
    return out
