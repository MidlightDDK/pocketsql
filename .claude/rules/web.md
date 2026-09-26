---
paths:
  - "web/**"
  - "worker/**"
---
# Web app + Worker

## Runtime
- Transformers.js v4: `AutoModelForCausalLM` + tokenizer for `MidlightDDK/pocketsql-<size>` pinned to a revision; `device: "webgpu"`, `dtype: "q4f16"`; fallback `device: "wasm"`, `dtype: "q4"` with a visible "slower mode" notice. Generation runs in a Web Worker; greedy; `max_new_tokens` 256.
- Post-process with `packages/sqlgen`: strip fences, keep the first statement, validate with DuckDB `EXPLAIN`. On failure, retry once with a second sample (temperature 0.3), then show the error honestly.
- DuckDB-WASM (pinned; jsDelivr bundles) with the 3 demo datasets (committed, ≤ 2 MB each) plus user upload (CSV or Parquet).

## UX
- Home: dataset picker, schema view, question box, and 6 example questions whose results are precomputed (instant while the model downloads). Download progress with MB, speed, and ETA; an "Offline ready" badge once the model and app are cached. The SQL is shown (editable and re-runnable), with a result table and an automatic chart for simple shapes.
- "Compare with a big model" (online only): calls `/api/compare` and shows both SQL queries and results side by side with agreement.
- `/evals`: tables from `latest.json` (base vs fine-tuned vs large API model; fp16 vs q4f16; per difficulty; cascade numbers), error-taxonomy examples, methodology. `/how`: pipeline diagram (data → Kaggle training → export → Hub → browser) with links to the kernel, dataset, and model card.

## Offline
PWA via vite-plugin-pwa: precache the app shell and the DuckDB-WASM files actually used; model files rely on the Transformers.js browser cache. The offline e2e test (evals rule) proves it.

## Headers (`web/public/_headers`)
CSP allowing self, jsDelivr (DuckDB and ONNX Runtime wasm), and the Hugging Face download hosts (`https://huggingface.co https://*.huggingface.co https://*.hf.co`) in `connect-src`; `script-src` with `'wasm-unsafe-eval'`; `object-src 'none'`; `base-uri 'none'`; `frame-ancestors 'none'`. Verify zero violations with Playwright; add the narrowest source if something is blocked, and note why.

## Worker (`worker/`)
- Serves `web/dist` (`not_found_handling "single-page-application"`, `run_worker_first ["/api/*"]`).
- `/api/session` (Turnstile) and `/api/compare {schemaId, question}` → one large-model call (reuse the provider chain from FilingLens if available; ask the user for its path) with a 5-per-minute per-IP rate limit. The big model gets the same prompt format. No other endpoints.

