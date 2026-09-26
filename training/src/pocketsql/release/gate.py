"""Eval gate (.claude/rules/training.md): no upload unless the ONNX artifact's test EX
reaches both the previous release and the base model.

`python -m pocketsql.release.gate --model pocketsql-0.5b-v1 [--write]` compares the
candidate's scored own_test rows in evals/reports/latest.json (every shipped dtype) with
evals/baseline.json (the last release) and with the base model's export in the same
runtime (like for like: the browser can only ever run a quantized base). After a pass
and the Hub upload (revision pinned in evalx/models.py), --write records the candidate
as the new baseline.
`--check <predictions.jsonl …>` (artifact-eval.yml) scores fresh predictions of the
pinned artifact and fails when EX falls more than TOLERANCE below the baseline.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from pocketsql.data import paths
from pocketsql.evalx.models import MODELS
from pocketsql.evalx.score import REPORT, score_file

BASELINE = paths.REPO / "evals" / "baseline.json"
TEST_SET = "own_test"
SHIPPED = ("onnx-q4f16-webgpu", "onnx-q4-cpu")
RECORDED_SETS = ("own_test", "spider_dev", "spider_dev_200", "val_50")
TOLERANCE = 0.02  # CPU kernels differ across machines; greedy text can drift slightly


def load_baseline() -> dict | None:
    if not BASELINE.exists():
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _is_base(model: str, base: str) -> bool:
    spec = MODELS.get(model, {})
    return model == base or (spec.get("base") == base and "run_id" not in spec)


def base_ex(base: str, runtime: str, results: list[dict]) -> float | None:
    """The base model's own_test EX in `runtime` (best of its exports), if scored."""
    scores = [
        r["ex"]
        for r in results
        if r["set"] == TEST_SET
        and r["runtime"] == runtime
        and _is_base(r["model"], base)
    ]
    return max(scores) if scores else None


def gate(
    model: str, results: list[dict], baseline: dict | None
) -> tuple[bool, list[str]]:
    """Return (passed, one line per shipped dtype)."""
    base = MODELS[model]["base"]
    rows = {
        r["runtime"]: r for r in results if r["model"] == model and r["set"] == TEST_SET
    }
    passed, lines = True, []
    for runtime in SHIPPED:
        row = rows.get(runtime)
        if row is None or row["missing"]:
            passed = False
            lines.append(f"{runtime}: FAIL (no complete {TEST_SET} predictions)")
            continue
        floor = base_ex(base, runtime, results)
        if floor is None:
            passed = False
            lines.append(f"{runtime}: FAIL (no {TEST_SET} result for {base} here)")
            continue
        prev = (baseline or {}).get("ex", {}).get(TEST_SET, {}).get(runtime)
        checks = [("base", floor)]
        checks += [("previous release", prev)] if prev is not None else []
        failed = [name for name, floor in checks if row["ex"] < floor]
        passed &= not failed
        vs = ", ".join(f"{name} {floor:.1%}" for name, floor in checks)
        verdict = f"FAIL (below {', '.join(failed)})" if failed else "ok"
        lines.append(f"{runtime}: EX {row['ex']:.1%} vs {vs}: {verdict}")
    return passed, lines


def new_baseline(model: str, results: list[dict]) -> dict:
    spec = MODELS[model]
    if not spec.get("revision"):
        raise SystemExit(f"pin {model}'s Hub revision in evalx/models.py first")
    ex: dict[str, dict[str, float]] = {}
    for r in results:
        if r["model"] == model and r["set"] in RECORDED_SETS:
            ex.setdefault(r["set"], {})[r["runtime"]] = r["ex"]
    return {
        "model": model,
        "hf_repo": spec["hf_repo"],
        "revision": spec["revision"],
        "run_id": spec["run_id"],
        "released": dt.date.today().isoformat(),
        "base": {
            "model": spec["base"],
            TEST_SET: {rt: base_ex(spec["base"], rt, results) for rt in SHIPPED},
        },
        "ex": {s: dict(sorted(ex[s].items())) for s in RECORDED_SETS if s in ex},
    }


def check(files: list[Path], baseline: dict) -> tuple[bool, list[str]]:
    """Fresh predictions of the released artifact vs its recorded EX."""
    passed, lines = True, []
    for path in files:
        summary, _ = score_file(path)
        want = baseline["ex"].get(summary["set"], {}).get(summary["runtime"])
        if summary["model"] != baseline["model"] or want is None:
            passed = False
            lines.append(f"{path.name}: FAIL (no baseline for this model/set/runtime)")
            continue
        ok = not summary["missing"] and summary["ex"] >= want - TOLERANCE
        passed &= ok
        lines.append(
            f"{path.name}: EX {summary['ex']:.1%} vs baseline {want:.1%} "
            f"(tolerance {TOLERANCE:.0%}): {'ok' if ok else 'FAIL'}"
        )
    return passed, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.release.gate")
    parser.add_argument("--model", choices=sorted(MODELS), help="release candidate")
    parser.add_argument("--write", action="store_true", help="record a new baseline")
    parser.add_argument("--check", nargs="+", type=Path, help="predictions to recheck")
    args = parser.parse_args(argv)
    baseline = load_baseline()
    if args.check:
        if baseline is None:
            raise SystemExit(f"{BASELINE.name} is missing")
        passed, lines = check(args.check, baseline)
    elif args.model:
        results = json.loads(REPORT.read_text(encoding="utf-8"))["results"]
        passed, lines = gate(args.model, results, baseline)
        if baseline:
            lines.insert(0, f"previous release: {baseline['model']}")
        if passed and args.write:
            BASELINE.write_text(
                json.dumps(new_baseline(args.model, results), indent=1) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            lines.append(f"wrote {BASELINE.relative_to(paths.REPO).as_posix()}")
    else:
        parser.error("--model or --check is required")
    print("\n".join(lines))
    print("gate: PASS" if passed else "gate: FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
