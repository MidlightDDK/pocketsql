---
paths:
  - "training/src/pocketsql/train/**"
  - "training/src/pocketsql/export/**"
  - "training/src/pocketsql/release/**"
  - "training/configs/**"
  - "kaggle/**"
---
# Training, export, release

## Base model selection (M2, data-driven)
Candidates: 2–3 permissively licensed models under 1B parameters that Transformers.js v4 supports (e.g. Qwen3-0.6B, Qwen2.5-Coder-0.5B-Instruct; check for newer ones in that size class). Choose by: (1) passes the export spike below, (2) zero-shot execution accuracy (EX) on 100 dev items, (3) quantized download size. Record the decision and its numbers in README "Design decisions". Heavier edge models (multi-GB downloads) are out of scope for a first visit.

## Export spike (M2, before any fine-tuning: this is the biggest project risk)
- Find out once how the official ONNX build of the candidate was produced (onnx-community model card and files such as `transformers.js_config` in `config.json`, plus the Transformers.js v4 docs); put the exact steps in `training/src/pocketsql/export/` with doc URLs.
- Re-export the unmodified base model yourself; produce q4f16 (WebGPU) and q4 (WASM); load both with Transformers.js v4 in Node; compare greedy outputs on 20 fixture prompts with PyTorch. fp32/fp16 ONNX must match on ≥ 18/20; report the quantized agreement rate. The user also loads it once in their browser through a minimal test page.
- If this path is blocked for more than one working day, stop and propose a fallback runtime: GGUF (llama.cpp conversion) with wllama (WASM), or WebLLM (MLC). Don't fine-tune until an export path works end to end.

## Training on Kaggle
- `kaggle/train/kernel-metadata.json`: `{"id": "<kaggle-username>/pocketsql-train", "title": "pocketsql-train", "code_file": "train.py", "language": "python", "kernel_type": "script", "is_private": true, "enable_gpu": true, "enable_internet": true}`.
- Accelerator: T4. Unsloth needs CUDA compute capability ≥ 7.0 and the P100 is 6.0. If the Kaggle CLI metadata can't select the GPU type (check its docs once), ask the user to set it in the Kaggle UI, or use TRL + PEFT, which runs on either GPU.
- `train.py` is self-contained: pinned pip installs; loads `<hf-username>/pocketsql-data` at a pinned revision; trains; evaluates on val (EX with DuckDB); merges; exports with the proven path; writes everything to `/kaggle/working/outputs/`.
- Flow: ask the user → `kaggle kernels push -p kaggle/train` → poll status at ≥ 5-minute intervals → `kaggle kernels output … -p training/runs/<run_id>/`.
- Method: LoRA SFT with Unsloth + TRL (fall back to TRL + PEFT if Unsloth fails to install). fp16, since T4 and P100 lack bf16. Loss on assistant tokens only. Starting point: r 16, alpha 32, dropout 0, all linear layers, lr 2e-4 cosine, 2 epochs, max_seq_len 1024, effective batch 32, seed 42. Change one thing per run.
- Each run writes `summary.json` (config, git SHA, dataset revision, GPU type, GPU minutes, train/val loss, val EX, wall time), which is committed. Checkpoints and weights never are.

## Export and release
- Merge LoRA → fp16 → ONNX via the proven path → q4f16 + q4 → `transformers.js_config` in `config.json` (default dtype per device) → tokenizer files.
- Parity: the shipped ONNX vs the merged PyTorch model on 50 val prompts (exact-match SQL rate and execution agreement), reported.
- Eval gate (`python -m pocketsql.release.gate`): the ONNX artifact's test EX must be ≥ the previous release and ≥ the base model; otherwise refuse to upload.
- Upload to `<hf-username>/pocketsql-<size>` with a model card: intended use, prompt format, training data and licenses, eval table (base vs fine-tuned vs large API model; fp16 vs q4f16), limitations, GPU hours used. The web app pins the exact Hub revision SHA.

