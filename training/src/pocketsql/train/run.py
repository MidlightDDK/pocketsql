"""One training run end to end; kaggle/train/train.py runs it on the GPU.

`python -m pocketsql.train.run --config training/configs/train_v1.yaml --out <dir>
[--work <dir>] [--data-dir training/data/processed] [--limit-train N] [--limit-val N]
[--max-steps N]` (the limits are for CPU smoke tests).

Data at the pinned Hub revision → base model val EX → LoRA SFT → merge → fine-tuned val
EX → fp16 merged checkpoint → ONNX (pocketsql.export.build) → <out>/summary.json.
"""

import argparse
import datetime as dt
import json
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import yaml

from pocketsql.data.leakage import read_jsonl
from pocketsql.evalx.models import MODELS
from pocketsql.train import evaluate, sft

# The merged checkpoint keeps the base model's tokenizer and generation settings.
BASE_FILES = ("generation_config.json", "tokenizer.json", "tokenizer_config.json")
PACKAGES = ("torch", "transformers", "trl", "peft", "accelerate", "onnxruntime-genai")


def fetch_data(cfg: dict, data_dir: Path | None, work: Path) -> tuple[Path, Path, Path]:
    if data_dir is None:
        from huggingface_hub import hf_hub_download

        repo, rev = cfg["dataset"]["repo"], cfg["dataset"]["revision"]
        get = lambda name: Path(  # noqa: E731
            hf_hub_download(repo, name, repo_type="dataset", revision=rev)
        )
    else:
        get = lambda name: data_dir / name  # noqa: E731
    dbs = work / "databases"
    with zipfile.ZipFile(get("databases.zip")) as z:
        z.extractall(dbs)
    return get("train.jsonl"), get("val.jsonl"), dbs


def val_ex(model, tok, cfg: dict, items: list[dict], dbs: Path, dest: Path) -> dict:
    sqls = evaluate.generate(
        model, tok, items, cfg["eval"]["batch_size"], cfg["eval"]["max_new_tokens"]
    )
    summary, outcomes = evaluate.score(items, sqls, dbs)
    with dest.open("w", encoding="utf-8", newline="\n") as f:
        for o in outcomes:
            f.write(json.dumps({**o, "sql": sqls[o["id"]]}, ensure_ascii=False) + "\n")
    print(f"{dest.stem}: EX {summary['ex']:.1%} on {summary['n']}", flush=True)
    return summary


def _version(pkg: str) -> str | None:
    try:
        return version(pkg)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.train.run")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work", type=Path, help="scratch space (default <out>/work)")
    parser.add_argument("--data-dir", type=Path, help="local files instead of the Hub")
    parser.add_argument("--limit-train", type=int)
    parser.add_argument("--limit-val", type=int)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--code-revision", help="git SHA of this code")
    parser.add_argument("--started", type=float, help="kernel start (epoch seconds)")
    args = parser.parse_args(argv)
    started = args.started or time.time()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    out, work = args.out, args.work or args.out / "work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer

    timings: dict[str, float] = {}
    clock = time.time()

    def lap(name: str) -> None:
        nonlocal clock
        timings[name] = round(time.time() - clock, 1)
        clock = time.time()
        print(f"[{name}] {timings[name]:.0f} s", flush=True)

    spec = MODELS[cfg["base_model"]]
    base_dir = Path(snapshot_download(spec["hf_repo"], revision=spec["revision"]))
    train_path, val_path, dbs = fetch_data(cfg, args.data_dir, work)
    train_rows = read_jsonl(train_path)[: args.limit_train]
    val_rows = read_jsonl(val_path)[: args.limit_val]
    tok = AutoTokenizer.from_pretrained(base_dir)
    max_len = cfg["train"]["max_seq_len"]
    train_fit, dropped = sft.fit_length(tok, train_rows, max_len)
    val_fit, _ = sft.fit_length(tok, val_rows, max_len)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    lap("setup")

    base = AutoModelForCausalLM.from_pretrained(base_dir, dtype=torch.float32)
    base_ex = val_ex(
        base.to(device).eval(), tok, cfg, val_rows, dbs, out / "val_base.jsonl"
    )
    del base
    lap("base_eval")

    merged, train_metrics = sft.train(
        cfg, base_dir, train_fit, val_fit, work, args.max_steps
    )
    lap("train")
    merged.gradient_checkpointing_disable()
    merged.config.use_cache = True
    ft_ex = val_ex(merged.eval(), tok, cfg, val_rows, dbs, out / "val_finetuned.jsonl")
    lap("finetuned_eval")

    model_dir = out / "merged"
    merged.to(torch.float16).save_pretrained(model_dir)
    for name in BASE_FILES:
        shutil.copyfile(base_dir / name, model_dir / name)
    # Same architecture, so keep the base config the export path was proven on
    # (transformers 5 rewrites rope_theta into rope_parameters and drops bos_token_id).
    config = json.loads((base_dir / "config.json").read_text(encoding="utf-8"))
    config["torch_dtype"] = "float16"
    (model_dir / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    del merged
    if device == "cuda":
        torch.cuda.empty_cache()
    lap("merge_save")

    summary = {
        "run_id": cfg["run_id"],
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_revision": args.code_revision,
        "config": cfg,
        "base_model": {"repo": spec["hf_repo"], "revision": spec["revision"]},
        "dataset": cfg["dataset"],
        "hardware": {
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "gpu_count": torch.cuda.device_count(),
            "cuda": torch.version.cuda,
            "python": platform.python_version(),
        },
        "versions": {p: _version(p) for p in PACKAGES},
        "data": {
            "train_pairs": len(train_fit),
            "train_by_source": dict(Counter(r["source"] for r in train_fit)),
            "train_dropped_over_max_len": len(dropped),
            "val_pairs": len(val_rows),
            "limits": {"train": args.limit_train, "val": args.limit_val},
        },
        "train": {**train_metrics, "max_steps_override": args.max_steps},
        "val_ex": {
            "base": base_ex,
            "finetuned": ft_ex,
            "delta_points": round((ft_ex["ex"] - base_ex["ex"]) * 100, 1),
        },
        "export": None,
        "timings_s": timings,
    }

    def write_summary() -> None:
        # The GPU session is held from kernel start, so wall time is GPU time.
        summary["wall_time_s"] = round(time.time() - started)
        summary["gpu_minutes"] = round((time.time() - started) / 60, 1)
        (out / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    write_summary()  # keep the training results even if the export fails
    onnx_dir = out / "onnx-model"
    dtypes = cfg["export"]["dtypes"]
    cmd = [sys.executable, "-m", "pocketsql.export.build", "--src", str(model_dir)]
    cmd += ["--out", str(onnx_dir), "--dtypes", *dtypes]
    try:
        subprocess.run(cmd, check=True)
        summary["export"] = {
            "dtypes": dtypes,
            "files_mib": {
                f.name: round(f.stat().st_size / 2**20, 1)
                for f in sorted((onnx_dir / "onnx").iterdir())
            },
        }
    except subprocess.CalledProcessError as e:
        summary["export"] = {"error": str(e)}
    lap("export")
    write_summary()
    print(json.dumps(summary["val_ex"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
