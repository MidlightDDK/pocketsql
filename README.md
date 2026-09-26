# PocketSQL

A small model I fine-tuned to turn plain-English questions into DuckDB SQL, quantized and running entirely in your browser (Transformers.js on WebGPU with a WASM fallback, DuckDB-WASM to execute the SQL). It keeps working with Wi-Fi off.

**Status:** scaffold (milestone M0). Placeholder: https://pocket-sql.azar-majed7.workers.dev

## Planned pipeline

Spider + synthetic data → LoRA fine-tune of a sub-1B open model on Kaggle's free GPUs → ONNX export (q4f16 / q4) → Hugging Face Hub → browser. Everything runs at $0: Kaggle, the Hugging Face Hub, Cloudflare Workers Free, and GitHub Actions.

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
```

## Design decisions

- Biome instead of ESLint + Prettier: one fast tool for linting and formatting with a single config file, and the same setup as my other projects.

More decisions (base model, export path, prompt format, data filtering, quantization) will be added with the numbers behind them.

## License

Code: MIT. Model, dataset, and third-party licenses will be listed here once they are chosen.
