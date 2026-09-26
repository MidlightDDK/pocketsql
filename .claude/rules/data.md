---
paths:
  - "training/src/pocketsql/data/**"
  - "training/src/pocketsql/synth/**"
  - "packages/sqlgen/**"
---
# Data, prompt format, schema serialization

## Sources
- Spider 1.0 (train + dev, including the SQLite databases) is the primary source. Use the official release or a well-known mirror that includes the databases; pin URL + sha256 in `training/data/sources.json`; verify the license and record it. If the scripted download is blocked, ask the user to download it manually. BIRD is far larger; consider only its dev set later, and only if disk allows.
- Demo schemas: the 3 openly licensed sample datasets shipped with the web app (licenses recorded).

## SQLite → DuckDB
- Load each Spider SQLite database into a DuckDB file (DuckDB's SQLite scanner or table-by-table export); log tables that fail.
- Transpile gold SQL with sqlglot (`read="sqlite", write="duckdb"`). Keep a pair only if the DuckDB result equals the SQLite result: order-insensitive unless the query has ORDER BY; float tolerance 1e-6; normalize int/float/str. Report the retention rate per database; typical losses come from integer division, loose typing, and case-sensitive comparisons.

## Synthetic data (in-domain for the demo schemas, plus diversity)
- Generator: an open-weight model whose license allows training on its outputs (gpt-oss, Apache-2.0), through Groq's free tier, batched and rate-limited. Check the provider's terms too. Never use proprietary-API outputs: their terms typically forbid training competing models. For large batches, run an Apache-2.0 open model on a Kaggle GPU instead of spending API quota.
- Per schema: generate diverse questions tagged by difficulty, with 3 SQL candidates each. Keep a pair only if ≥ 2 candidates execute and agree on the result, and the result is non-empty and deterministic.
- Dedupe (normalized question + normalized SQL) and drop anything close to a test item: exact normalized match, or token-Jaccard ≥ 0.9 on questions for the same schema.
- The user reviews 50 random kept pairs; report the acceptance rate in the dataset card.

## Prompt format (identical in training, evals, and the browser)
- The base model's chat template with thinking disabled (Qwen3 family: `enable_thinking=False`).
- System: "Write one DuckDB SQL query that answers the question. Output only SQL."
- User: compact schema DDL (`CREATE TABLE t (col TYPE, …);`, one line per table; up to 2 example values for text columns with ≤ 20 distinct values), then `Question: …`.
- Assistant: the SQL only, no code fences, ending with `;`.
- The serializer exists twice (Python `pocketsql.data.schema`, TS `packages/sqlgen`). Both must reproduce `packages/sqlgen/fixtures/golden/*.txt` byte-for-byte, and the tokenized prompt ids must match between the Python tokenizer and Transformers.js for 5 fixtures (tests in both languages).

## Outputs
- `training/data/processed/{train,val}.jsonl`: `{id, db_id, schema_text, question, sql, source, difficulty}`.
- Pushed as a public Hugging Face dataset `<hf-username>/pocketsql-data`, including an archive of the DuckDB database files needed for val/test scoring, with a card: sources, licenses (Spider-derived data keeps Spider's license terms), filters, retention rates, review stats.
- Test sets live in `evals/` and are never used for training or synthetic seeding. A leakage check script runs in CI.

