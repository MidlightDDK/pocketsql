---
paths:
  - "evals/**"
  - "training/src/pocketsql/evalx/**"
  - ".github/**"
---
# Evals + CI

## Test sets (committed; never used for training or synthetic seeding)
- `evals/sets/spider_dev_duckdb.jsonl`: Spider dev pairs that survived conversion (report the size).
- `evals/sets/own_test.jsonl`: 100 questions over the 3 demo schemas, spread across difficulty tags; the user verifies every SQL.
- Item: `{id, db_id, question, gold_sql, gold_result_hash, difficulty}`.

## Predictions → one scorer
- Producers write `evals/predictions/<model>__<runtime>__<set>.jsonl` (`{id, sql, latency_ms, tokens_out}`): PyTorch (on Kaggle, or a CPU subset locally), the ONNX artifact through Transformers.js in Node (`pnpm eval:onnx`), and the large API baseline through Groq (same prompt, temperature 0; calls cached in `.cache/`).
- A single Python scorer (`python -m pocketsql.evalx.score`) scores every runtime identically.
- Metrics: execution accuracy (EX; result-set match as defined in the data rule), valid-SQL rate, exact match (secondary), latency p50/p95, download size, API calls per 100 questions, per-difficulty breakdown. Browser speed comes from `pnpm bench:browser` run by the user on real devices; record device and browser.
- Error taxonomy (auto-tagged, plus manual notes on 30 failures): wrong column or table, join error, aggregation, date/time functions, dialect error, hallucinated schema, formatting.
- Cascade (with Browser Analyst): local model first; escalate when the SQL fails to parse or execute, returns empty where a non-empty result is expected (heuristic), or two samples disagree. Report % answered locally, the cascade's EX vs the big model alone, and API calls saved.

## Reports
`evals/reports/latest.json` (plus dated copies on release) feeds the web app; a Markdown table goes into PR comments.

## CI (`.github/workflows/`)
- `ci.yml` (PRs and main): ruff + pytest, lint/typecheck/vitest, serializer golden tests in both languages, leakage check, web build, Playwright with a stub generator. Nothing here needs a GPU or a model download.
- `artifact-eval.yml` (workflow_dispatch + weekly): download the pinned ONNX artifact (actions/cache), run `pnpm eval:onnx` on `own_test` + 200 Spider-dev items on CPU, score, gate against `evals/baseline.json`.
- `e2e-real.yml` (main + workflow_dispatch): Playwright with the real model (cached): load → go offline (`context.setOffline(true)`) → ask 3 questions → results render.
- `deploy.yml` (push to main) and `smoke.yml` (daily: load the page, run one precomputed example; open an issue on failure).
- Least-privilege `permissions` per job; skip steps that need secrets when they are absent (forks).

