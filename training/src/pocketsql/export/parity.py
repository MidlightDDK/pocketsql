"""Export parity: ONNX greedy outputs vs PyTorch on the 20 parity prompts.

`python -m pocketsql.export.parity --reference <model>__torch-cpu
--candidates <name>__onnx-<dtype>-<device> … [--set val_50] [--report]` compares each
candidate's `__<set>` file with the reference. For the default `parity` set (20 prompts,
M2) the reference comes from its own_test/spider_dev_100 files; `val_50` is the release
parity check (shipped ONNX vs merged PyTorch on 50 val prompts, M5).
Gate (.claude/rules/training.md): the unquantized (fp32) export must match on ≥ 18/20
prompts; fp16 and the 4-bit variants are reported, since fp16 drifts from fp32 PyTorch.
"""

import argparse
import datetime as dt
import json

import duckdb

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx.compare import has_order_by, results_match, run_duckdb
from pocketsql.evalx.postprocess import clean_sql
from pocketsql.evalx.score import REPORT, connect
from pocketsql.evalx.sets import PARITY, load_set

PREDICTIONS = paths.REPO / "evals" / "predictions"
MIN_MATCH = 18


def _result(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple] | None:
    try:
        return run_duckdb(con, sql, 10.0) if sql else None
    except duckdb.Error:
        return None


def compare(reference: str, candidate: str, set_name: str = "parity") -> dict:
    bases = PARITY if set_name == "parity" else (set_name,)
    ref = {
        p["id"]: p["sql"]
        for base in bases
        for p in read_jsonl(PREDICTIONS / f"{reference}__{base}.jsonl")
    }
    cand = {
        p["id"]: p["sql"]
        for p in read_jsonl(PREDICTIONS / f"{candidate}__{set_name}.jsonl")
    }
    same_text = same_result = 0
    items = load_set(set_name)
    for item in items:
        a, b = ref[item["id"]].strip(), cand[item["id"]].strip()
        same_text += a == b
        with connect(item["db_id"]) as con:
            ra, rb = _result(con, clean_sql(a)), _result(con, clean_sql(b))
        try:
            ordered = has_order_by(clean_sql(a))
        except Exception:
            ordered = False
        same_result += (ra is None and rb is None) or (
            ra is not None and rb is not None and results_match(ra, rb, ordered)
        )
    return {
        "reference": reference,
        "candidate": candidate,
        "set": set_name,
        "n": len(items),
        "same_output": same_text,
        "same_result": same_result,
        "checked": dt.date.today().isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.export.parity")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidates", nargs="+", required=True)
    parser.add_argument("--set", default="parity", choices=("parity", "val_50"))
    parser.add_argument("--report", action="store_true", help="update latest.json")
    args = parser.parse_args(argv)
    rows = [compare(args.reference, c, args.set) for c in args.candidates]
    failed = False
    for r in rows:
        gated = "-fp32-" in r["candidate"]
        ok = not gated or r["same_output"] >= MIN_MATCH
        failed |= not ok
        print(
            f"{r['candidate']}: same output {r['same_output']}/{r['n']}, "
            f"same result {r['same_result']}/{r['n']}"
            + ("" if ok else f" (FAIL: needs {MIN_MATCH})")
        )
    if args.report:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        keep = [
            p
            for p in report.get("export_parity", [])
            if (p["candidate"], p.get("set", "parity"))
            not in {(c, args.set) for c in args.candidates}
        ]
        report["export_parity"] = sorted(
            keep + rows, key=lambda p: (p.get("set", "parity"), p["candidate"])
        )
        REPORT.write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
