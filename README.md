# PocketSQL

A small model I fine-tuned to turn plain-English questions into DuckDB SQL, quantized and running entirely in your browser (Transformers.js on WebGPU with a WASM fallback, DuckDB-WASM to execute the SQL). It keeps working with Wi-Fi off.

**Status:** model v2 released as [MidlightDDK/pocketsql-0.5b](https://huggingface.co/MidlightDDK/pocketsql-0.5b) (milestone M5): 45% execution accuracy on the demo-database test set vs 29% for the base model, both as the 4-bit files a browser loads. The offline web app (M6) is next. Placeholder: https://pocket-sql.azar-majed7.workers.dev

## Planned pipeline

Spider + synthetic data → LoRA fine-tune of a sub-1B open model on Kaggle's free GPUs → ONNX export (q4f16 / q4) → Hugging Face Hub → browser. Everything runs at $0: Kaggle, the Hugging Face Hub, Cloudflare Workers Free, and GitHub Actions.

## Data

Spider's SQLite databases and gold queries, converted to DuckDB and kept only when DuckDB returns the same result as SQLite: 7,376 train and 858 val pairs (val = 16 held-out databases), plus a 981-item Spider-dev test set in `evals/sets/`. Retention is 95.9% (train), 92.8% (val), and 94.9% (dev); per-database numbers are in `training/data/cards/stats.json`. On top of that, 591 synthetic pairs over the three demo schemas: gpt-oss-120b writes questions with SQL, gpt-oss-20b and Qwen3.8-27B answer them independently, and a pair is kept only when 2 of the 3 queries return the same non-empty, order-independent result and it is not close to a test item (52% of 1,128 questions kept; a 50-pair review accepted 88%). Published as [MidlightDDK/pocketsql-data](https://huggingface.co/datasets/MidlightDDK/pocketsql-data). The app's demo databases (Chinook, Palmer penguins, World Bank indicators) are in `web/public/data/`.

## Repo layout

- `training/`: Python 3.12 (uv) package `pocketsql`: data, synthetic pairs, training, export, scoring, release gate.
- `kaggle/train/`: the Kaggle training kernel.
- `packages/sqlgen/`: TypeScript schema serializer, prompt builder, and SQL post-processing.
- `evals/`: test sets, predictions, reports, and the ONNX eval runner.
- `web/`: Vite + React + Tailwind app. `worker/`: Cloudflare Worker that serves it.

## Develop

```sh
uv sync --project training && pnpm i
uv run --project training ruff check -q && uv run --project training pytest -q
pnpm -s lint && pnpm -s typecheck && pnpm -s test && pnpm -s e2e
pnpm dev
uv run --project training python -m pocketsql.data.prepare  # Spider → DuckDB pairs
uv run --project training python -m pocketsql.data.demo     # demo DuckDB files
kaggle kernels push -p kaggle/train                          # LoRA run on a Kaggle T4 (training/configs/)
```

## Design decisions

- Biome instead of ESLint + Prettier: one fast tool for linting and formatting with a single config file, and the same setup as my other projects.

- Prompt schema as compact DDL, one `CREATE TABLE` line per table, with up to 2 example values for low-cardinality text columns. The same serializer exists in Python and TypeScript; both reproduce 6 golden fixtures byte for byte, and Transformers.js tokenizes them to the same ids as Python `transformers`.
- Data filtering by execution, not by string rules: a Spider query is kept only if its DuckDB translation returns SQLite's result. Four rewrites keep SQLite's meaning (double-quoted strings → literals, `LIKE` → `ILIKE`, bare columns added to `GROUP BY`, no `NULLIF`/`NULLS FIRST` guards); they took retention from 88.5% to 95.9% on train.
- Demo databases use 16 KiB DuckDB blocks: the default 256 KiB blocks made Chinook 3 MB; now it is 684 KiB (readable by DuckDB ≥ 1.2).

- Base model: **Qwen2.5-Coder-0.5B-Instruct** (Apache-2.0), chosen over Qwen3-0.6B and Qwen3.5-0.8B on zero-shot execution accuracy (EX) of the artifact the browser would load, then download size. Scored on `own_test` (100 questions over the demo databases) and the first 100 Spider-dev items; greedy decoding, same prompt everywhere, PyTorch on CPU and ONNX through Transformers.js 4.3.0 in Node:

  | Model | Runtime | own_test EX | Spider-dev EX | Browser download |
  |---|---|---|---|---|
  | gpt-oss-120b (Groq API, reference) | API | 77% | 73% | none, ~$0.0001/query |
  | **Qwen2.5-Coder-0.5B-Instruct** | PyTorch fp32 | 36% | 39% | |
  | | **ONNX q4f16 (our export)** | **29%** | **32%** | **276 MiB** |
  | Qwen3-0.6B | PyTorch fp32 | 29% | 42% | |
  | | ONNX q4f16 (our export) | 20% | 30% | 341 MiB |
  | | ONNX q4f16, k-quant + int8 layers | 21% | 37% | 477 MiB |
  | | ONNX q4f16 (onnx-community) | 19% | 32% | 552 MiB |
  | Qwen3.5-0.8B | PyTorch fp32 | 29% | 21% | 576 MiB (onnx-community) |

  Qwen3-0.6B's 3-point Spider-dev lead in PyTorch is within noise at n = 100 (±5 points); after 4-bit quantization the coder model is ahead on both sets combined (61 vs 58 of 200 for Qwen3's best recipe) at 58% of the download. Full numbers: `evals/reports/latest.json`.
- Export path: the ONNX Runtime GenAI model builder, the tool behind the onnx-community Qwen ONNX builds, then two fixes for Transformers.js (KV-cache head dimension pinned, `transformers.js_config` in `config.json`). The fp32 export matches PyTorch greedy output on 20/20 parity prompts for both finalists. 4-bit quantization (int4, block 32) changes the text of 16/20 outputs but keeps the DuckDB result on 13/20; that drop is the fine-tuning target, and the numbers I report come from the quantized artifact. The unmodified export is [MidlightDDK/pocketsql-base-0.5b](https://huggingface.co/MidlightDDK/pocketsql-base-0.5b).
- Browser check (Chrome 153, Windows, Intel Gen9 integrated GPU): the q4f16 model loads over WebGPU in 63 s on first visit and answers in 9–11 s; the WASM fallback (q4) gives the same SQL in 50–112 s, single-threaded. Two fixes came out of it: huggingface.co answers requests whose Referer is a `*.workers.dev` page with a 404, so model downloads go out with no referrer; and ONNX Runtime Web's WASM build lacks the quantized-embedding op (`GatherBlockQuantized`) that the builder emits for tied embeddings, so the q4 graph gathers the packed int4 rows and dequantizes them with standard ops (bit-identical logits, same file size).
- Training: LoRA SFT (r 16, alpha 32, all linear layers, 2 epochs, effective batch 32, lr 2e-4 cosine) on one Kaggle T4 in fp16 mixed precision, with the loss on the SQL only. The plan was Unsloth, but its current release requires transformers ≤ 5.5 and TRL ≤ 0.24, while the tokenizer and export parity checks rely on transformers 5.17, so it runs on plain TRL + PEFT; for a 0.5B model that takes 48 minutes. Run v1 (Spider only, 7,227 pairs that fit in 1,024 tokens): validation EX went from 43.2% to 59.9% (greedy decoding in PyTorch, 858 questions on 16 held-out databases) and valid SQL from 58.6% to 78.4%, with the largest gain on extra-hard questions (13% to 45%). The whole kernel took 58 GPU minutes, including both evaluations and the q4f16/q4 export; the exported model loads in Node through Transformers.js. Numbers: `training/runs/v1/summary.json`.
- Release gate: a model ships only if its 4-bit artifact's execution accuracy (EX) on `own_test` reaches the base model's 4-bit export in the same runtime and the previous release (`python -m pocketsql.release.gate`, thresholds in `evals/baseline.json`; a weekly workflow reruns the released artifact against them). Run v1 was refused: training on Spider alone raised Spider-dev EX from 30.9% to 47.2% (q4f16, 981 questions) but dropped `own_test` from 29% to 20%, because Spider habits (aggregates listed first, `= 'unknown'` for NULLs, missed joins) do not fit the demo schemas. Run v2 changed one thing, adding the 591 synthetic pairs, and passed: `own_test` 45% (q4f16) and 43% (q4) vs 29% and 30% for the base export, Spider-dev 49.3% at the same validation EX (60.0%). Numbers: `evals/reports/latest.json`, model card on the Hub.
- Quantization cost: on 50 validation prompts the 4-bit graphs return the same result as the merged PyTorch model on 31/50, and EX drops from 60% to 54% (49% to 45% on `own_test`). Exporting run v1 with the builder's k-quant algorithm instead of round-to-nearest raised that agreement to 40/50 for 7 MiB more (+1 point on 200 Spider-dev items, +2 on `own_test`); it needs zero-point support in the WASM embedding rewrite before it can ship, so it is the first iteration after M5.
- Scoring: 36 Spider-dev gold queries depend on ties or row order (e.g. `ORDER BY count(*) DESC LIMIT 1` with ties), so their stored result hash cannot be reproduced. The scorer reruns those gold queries instead of failing, and still aborts on any other mismatch.

## License

Code: MIT. Data:

- [Spider](https://yale-lily.github.io/spider) (Yu et al., 2018): CC BY-SA 4.0. The derived dataset `MidlightDDK/pocketsql-data` keeps that license.
- [Chinook](https://github.com/lerocha/chinook-database): MIT.
- [Palmer penguins](https://allisonhorst.github.io/palmerpenguins/) (Gorman, Williams & Fraser, 2014): CC0 1.0.
- [World Development Indicators](https://datacatalog.worldbank.org/search/dataset/0037712), World Bank: CC BY 4.0 (snapshot retrieved 2026-09-26).
- Synthetic pairs: generated with gpt-oss-120b and gpt-oss-20b (OpenAI) and Qwen3.8-27B (Qwen team), all Apache-2.0, through the Groq API (outputs belong to the customer under Groq's terms).

Base model: [Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct) (Qwen team): Apache-2.0.
