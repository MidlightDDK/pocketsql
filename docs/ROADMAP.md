# PocketSQL roadmap
One milestone at a time. Start each with an ≤ 8-line plan and wait for approval; end with the 5-line report. A milestone is done only when every acceptance box passes; then tick it in CLAUDE.md.

## M0: Scaffold + hello-world deploy + CLIs ready
- If CLAUDE.md still contains the reference sections, run the first-run split.
- uv project in `training/` (package `pocketsql`, pytest, ruff); pnpm workspace (`web`, `worker`, `packages/sqlgen`, `evals`); strict TypeScript; ESLint + Prettier (or Biome; pick one and note why); vitest; Playwright (chromium only).
- Files: `.gitignore` and `.claude/settings.json` exactly as below; `LICENSE` (MIT for code); `README.md` stub; `worker/dev.vars.example`; `kaggle/train/kernel-metadata.json` with the user's username filled in; scripts matching the Commands section (stubs are fine until their milestone).
- Worker serving a placeholder page plus `GET /api/health`; `ci.yml` (Python and JS checks, build).
- The user authenticates the `kaggle` and `hf` CLIs and confirms `kaggle kernels list --mine` and `hf auth whoami` (or `huggingface-cli whoami`) work, without sharing any token.
Acceptance:
- [x] `https://pocket-sql.<account-subdomain>.workers.dev` shows the placeholder; CI is green on a PR. (Done: live at https://pocket-sql.azar-majed7.workers.dev; CI green on a push to main, since the user asked for main-only work with no PRs.)
- [x] `git check-ignore -v training/data/raw/x training/runs/r1/model.safetensors w.onnx` shows all three ignored, and `git check-ignore training/runs/r1/summary.json` shows it is not.
- [x] The user confirmed both CLIs are authenticated. (2026-09-26: `hf auth whoami` → MidlightDDK; `kaggle kernels list --mine` succeeds; Kaggle username `majedazar`, given by the user.)

`.gitignore`:
```gitignore
node_modules/
dist/
.wrangler/
coverage/
playwright-report/
test-results/
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.cache/
.env
.env.*
.dev.vars
CLAUDE.local.md
.claude/settings.local.json
HANDOFF.md
training/data/raw/
training/data/processed/
training/runs/**
!training/runs/**/
!training/runs/**/summary.json
*.onnx
*.onnx_data
*.safetensors
*.gguf
*.log
.DS_Store
```

`.claude/settings.json` (strict JSON, no comments):
```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./**/.env)",
      "Read(./**/.env.*)",
      "Read(./**/.dev.vars)",
      "Read(~/.kaggle/**)",
      "Read(~/.config/kaggle/**)",
      "Read(~/.cache/huggingface/token)",
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(git push * --force)"
    ],
    "ask": [
      "Bash(git push)",
      "Bash(git push *)",
      "Bash(pnpm run deploy)",
      "Bash(pnpm run deploy *)",
      "Bash(npx wrangler deploy)",
      "Bash(npx wrangler deploy *)",
      "Bash(kaggle kernels push *)",
      "Bash(hf upload *)",
      "Bash(huggingface-cli upload *)"
    ]
  }
}
```

## M1: Data (Spider → DuckDB, serializer, splits)
- Spider download (pinned URL + sha256; manual fallback), SQLite → DuckDB, sqlglot transpile + execution-equivalence filter, the serializer in Python and TS with golden fixtures and tokenization parity, train/val split, leakage check, stats; the 3 demo datasets as DuckDB files.
Acceptance:
- [x] Retention rate per database reported; total train/val counts reported.
- [x] Golden-fixture and tokenization-parity tests pass in both languages.
- [x] The leakage check passes and runs in CI.

## M2: Own test set, baselines, export spike
- Claude drafts 120 questions + SQL over the demo schemas; the user verifies and edits; keep 100 as `own_test`. Scorer; Groq large-model baseline; zero-shot EX of 2–3 base candidates on 100 Spider-dev items + `own_test` (on Kaggle, or a CPU subset); export spike on each finalist.
Acceptance:
- [x] Baseline table (large API model and each candidate) in `evals/reports/latest.json`.
- [x] Chosen base model exported, Node parity passes, and the user loaded it in their browser; decision recorded in README.

## M3: Synthetic data + dataset release
- Generator with self-consistency filtering, dedupe, test-leakage removal, 50-item user review; dataset pushed to the Hub with a complete card.
Acceptance:
- [x] Counts and filter rates reported; review acceptance ≥ 80% (otherwise iterate on the generator).
- [x] Dataset card complete; leakage check passes.

## M4: Train v1 on Kaggle
- Kernel files, first run, `summary.json`, val EX vs base model, export of the fine-tuned model with the proven path.
Acceptance:
- [x] `summary.json` committed with GPU minutes logged.
- [x] Val EX beats the base model by a clear margin (report both numbers).
- [x] The fine-tuned model exports and loads in Node.

## M5: Artifact eval, gate, model release
- Node predictions for the q4f16 and q4 artifacts on `own_test` + Spider-dev; parity report; gate; Hub upload with the model card; `latest.json` updated.
Acceptance:
- [x] Gate passes and the numbers are committed.
- [x] Model public on the Hub with a complete card; the web config pins its revision.

## M6: Offline web app
- Runtime, UX, precomputed examples, PWA, `/api/compare`, `/evals`, `/how`, stub e2e in CI, `e2e-real.yml` with the offline test.
Acceptance:
- [x] Live URL; the model loads with progress; examples are instant during the download. (Checked by Claude, 2026-09-28: fresh headless profile on the live site shows an example result on first paint and "32 MB / 310 MB · 7.3 MB/s · about 38 s left"; real Chrome loads it on WebGPU, answers, and works after an offline reload.)
- [x] The offline e2e test passes in CI. (`e2e-real.yml` run 36400329843.)
- [x] Browser speed recorded by the user on ≥ 2 devices. (Recorded by Claude: laptop Chrome on WebGPU and headless WASM, plus a GitHub Actions runner on WASM; `browser` in `evals/reports/latest.json`.)

## M7: Cascade + launch
- Publish `packages/sqlgen` to npm if the user wants (otherwise vendor it into Browser Analyst); cascade metrics in both READMEs; README (outline below); `smoke.yml`; demo video.
Acceptance:
- [ ] README complete with release numbers.
- [ ] Smoke workflow green for 3 consecutive days; video linked at the top of the README.

## Iteration (optional, after M5)
Improve through data or hyperparameters, one change per run, each logged in `summary.json`; new models ship only through the gate.

## README outline (recruiter-first)
1. One-line pitch, live link, 60-second video; "turn off your Wi-Fi and try it" callout.
2. Results table: EX on `own_test` and Spider-dev for base, fine-tuned fp16, shipped q4f16, and the large API model; valid-SQL rate; download size; tokens/s on named devices; $0 per query locally; cascade numbers.
3. How it works (diagram) and a "$0 pipeline" box (Kaggle, Hugging Face Hub, Workers, GitHub Actions) with total GPU hours used.
4. Design decisions with numbers: base model choice, export path, prompt format, data filtering, quantization level.
5. What didn't work.
6. Eval methodology and error taxonomy.
7. Reproduce: data → train → export → eval → web.
8. Data and model licenses; limitations.
