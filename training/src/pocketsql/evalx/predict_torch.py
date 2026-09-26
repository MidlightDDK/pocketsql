"""Zero-shot PyTorch predictions on CPU (greedy, thinking disabled).

`uv run --project training --group infer python -m pocketsql.evalx.predict_torch
--model qwen3-0.6b --set own_test [--path <local dir>]` writes
evals/predictions/<model>__torch-cpu__<set>.jsonl and resumes an interrupted run;
--path loads local weights (a run's merged model) instead of the pinned Hub revision.
"""

import argparse
import json
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from pocketsql.data import paths
from pocketsql.data.leakage import read_jsonl
from pocketsql.data.schema import messages
from pocketsql.evalx.models import MODELS
from pocketsql.evalx.sets import SET_NAMES, load_schemas, load_set

PREDICTIONS = paths.REPO / "evals" / "predictions"
MAX_NEW_TOKENS = 256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.predict_torch")
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--set", required=True, choices=SET_NAMES)
    parser.add_argument("--limit", type=int, help="first N items only")
    parser.add_argument("--path", help="local model dir instead of the Hub revision")
    args = parser.parse_args(argv)
    spec = MODELS[args.model]
    out = PREDICTIONS / f"{args.model}__torch-cpu__{args.set}.jsonl"
    done = {p["id"] for p in read_jsonl(out)} if out.exists() else set()
    items = [i for i in load_set(args.set)[: args.limit] if i["id"] not in done]
    schemas = load_schemas()

    source = (
        {"pretrained_model_name_or_path": args.path}
        if args.path
        else {
            "pretrained_model_name_or_path": spec["hf_repo"],
            "revision": spec["revision"],
        }
    )
    tok = AutoTokenizer.from_pretrained(**source)
    model = AutoModelForCausalLM.from_pretrained(**source, dtype=torch.float32).eval()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8", newline="\n") as f:
        for n, item in enumerate(items, 1):
            ids = tok.apply_chat_template(
                messages(schemas[item["db_id"]], item["question"]),
                add_generation_prompt=True,
                enable_thinking=False,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
            start = time.perf_counter()
            with torch.inference_mode():
                gen = model.generate(
                    **ids, max_new_tokens=MAX_NEW_TOKENS, do_sample=False
                )
            latency = (time.perf_counter() - start) * 1000
            new = gen[0, ids["input_ids"].shape[1] :]
            row = {
                "id": item["id"],
                "sql": tok.decode(new, skip_special_tokens=True),
                "latency_ms": round(latency, 1),
                "tokens_out": int(new.shape[0]),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if n % 10 == 0:
                print(f"{n}/{len(items)} {latency:.0f} ms", flush=True)
    print(f"wrote {out.relative_to(paths.REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
