# PocketSQL

A small model I fine-tuned to turn plain-English questions into DuckDB SQL, quantized and running entirely in your browser (Transformers.js on WebGPU with a WASM fallback, DuckDB-WASM to execute the SQL). It keeps working with Wi-Fi off.

**Status:** data pipeline done (milestone M1). Placeholder: https://pocket-sql.azar-majed7.workers.dev

## Planned pipeline

Spider + synthetic data → LoRA fine-tune of a sub-1B open model on Kaggle's free GPUs → ONNX export (q4f16 / q4) → Hugging Face Hub → browser. Everything runs at $0: Kaggle, the Hugging Face Hub, Cloudflare Workers Free, and GitHub Actions.

## Data

Spider's SQLite databases and gold queries, converted to DuckDB and kept only when DuckDB returns the same result as SQLite: 7,376 train and 858 val pairs (val = 16 held-out databases), plus a 981-item Spider-dev test set in `evals/sets/`. Retention is 95.9% (train), 92.8% (val), and 94.9% (dev); per-database numbers are in `training/data/cards/stats.json`. Published as [MidlightDDK/pocketsql-data](https://huggingface.co/datasets/MidlightDDK/pocketsql-data). The app's demo databases (Chinook, Palmer penguins, World Bank indicators) are in `web/public/data/`.

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
```

## Design decisions

- Biome instead of ESLint + Prettier: one fast tool for linting and formatting with a single config file, and the same setup as my other projects.

- Prompt schema as compact DDL, one `CREATE TABLE` line per table, with up to 2 example values for low-cardinality text columns. The same serializer exists in Python and TypeScript; both reproduce 6 golden fixtures byte for byte, and Transformers.js tokenizes them to the same ids as Python `transformers`.
- Data filtering by execution, not by string rules: a Spider query is kept only if its DuckDB translation returns SQLite's result. Four rewrites keep SQLite's meaning (double-quoted strings → literals, `LIKE` → `ILIKE`, bare columns added to `GROUP BY`, no `NULLIF`/`NULLS FIRST` guards); they took retention from 88.5% to 95.9% on train.
- Demo databases use 16 KiB DuckDB blocks: the default 256 KiB blocks made Chinook 3 MB; now it is 684 KiB (readable by DuckDB ≥ 1.2).

More decisions (base model, export path, quantization) will be added with the numbers behind them.

## License

Code: MIT. Data:

- [Spider](https://yale-lily.github.io/spider) (Yu et al., 2018): CC BY-SA 4.0. The derived dataset `MidlightDDK/pocketsql-data` keeps that license.
- [Chinook](https://github.com/lerocha/chinook-database): MIT.
- [Palmer penguins](https://allisonhorst.github.io/palmerpenguins/) (Gorman, Williams & Fraser, 2014): CC0 1.0.
- [World Development Indicators](https://datacatalog.worldbank.org/search/dataset/0037712), World Bank: CC BY 4.0 (snapshot retrieved 2026-09-26).

The base model's license will be listed once it is chosen (M2).
