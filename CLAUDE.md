<!--
PocketSQL: single-file brief for Claude Code.
Setup (human): create an empty PUBLIC GitHub repo named pocket-sql, clone it, save this file as CLAUDE.md in the
repo root, start Claude Code there and say: Start M0. You will need free Kaggle (phone-verified for GPU) and
Hugging Face accounts; neither needs a card.
On the first run Claude splits this file with one awk command. The part before the first split marker stays
in CLAUDE.md (loaded every session, under 200 lines). Each later section moves to .claude/rules/ (loaded only
when Claude reads matching files) or docs/ (read on demand). HTML comments like this one are stripped from
Claude's context, so they cost no tokens.
-->
# PocketSQL: a small model I fine-tuned, running offline in your browser

## Mission
AI Engineer portfolio project. Fine-tune an open model under 1B parameters to turn plain-English questions into DuckDB SQL for a given schema, quantize it, and run it entirely in the browser (Transformers.js v4 on WebGPU, WASM fallback), with DuckDB-WASM executing the SQL. A recruiter opens the URL, the model downloads once, and the demo keeps working with Wi-Fi off. An eval page compares the shipped model with its base model and a large API model on execution accuracy, speed, size, and cost per query. The model later becomes tier 0 of a cascade in the Browser Analyst project.

## Hard constraints (never violate)
- $0: GPU work only on Kaggle's free GPUs (~30 h/week; keep a GPU-hours log); hosting on Cloudflare Workers Free and the Hugging Face Hub (public repos); CI on GitHub Actions. No paid clouds, no payment methods. If anything would need a card, stop and ask.
- Public repo: no secrets or tokens (Kaggle, Hugging Face, Groq), no checkpoints, model weights, or datasets in git. Weights and datasets go to the Hugging Face Hub.
- License hygiene: the base model, datasets, and synthetic-data generator must allow training and redistribution; record each with its license in the model card and README.
- Ship what you measured: reported numbers come from the exact artifact the browser loads (quantized ONNX), with PyTorch numbers only as context.
- Eval gate: never publish a model whose test execution accuracy is below the previous release or below the base model.
- Recruiter-first: the first visit shows a working demo immediately (precomputed example results) while the model downloads with visible progress; clear fallback when WebGPU is missing.

## Token efficiency rules
Apply to every task. Aim: a correct result using the least context and output. Never trade away correctness, or verification the task genuinely needs, to save tokens.

### Scope
- Do exactly what was asked. No unrequested refactors, renames, reformatting, dependency changes, or extra features; mention other problems you notice in one line instead.
- Ambiguous request: ask one focused question before starting. Large change (many files or an architectural choice): outline the plan in 8 lines or fewer and wait for approval, unless a plan was already approved or the user asked you to proceed on your own.
- `docs/ROADMAP.md` is approved at milestone level only. At the start of each milestone, read only that milestone's section (`grep -n '^## ' docs/ROADMAP.md`, then read that range), post an ≤8-line plan, and wait for approval.

### Reading and searching
- Locate before reading: Grep/Glob (or the LSP tool if available), then Read only the relevant range. Check length (`wc -l`) before opening an unfamiliar file; for files over ~300 lines, read only the ranges you need.
- Don't re-read files already in context unless they changed or you only saw part of them.
- Put independent searches and reads in the same turn (parallel tool calls).
- Never scan the whole repo (`ls -R`, `tree`, unscoped `find` or grep). Scope to the relevant directory.
- Don't open unless the task requires it: `.git/`, `node_modules/`, `web/dist/`, `.wrangler/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `coverage/`, `playwright-report/`, `test-results/`, lockfiles (`pnpm-lock.yaml`, `uv.lock`), minified bundles, source maps, generated code, snapshots, `training/data/`, everything in `training/runs/` except `summary.json`, `.cache/` dirs, model files (`*.onnx`, `*.onnx_data`, `*.safetensors`, `*.gguf`, `*.bin`), the Hugging Face cache, binaries, media. If one is needed, inspect its shape first (`head -n 3`, `wc -l`, `jq 'keys'`, `du -sh`, a targeted grep).
- Prefer the repo over the web. Search or fetch only when the answer isn't local, and fetch the specific page, not the whole site. Record what you looked up (export command, model ID, CLI flag, pinned version) where it is used, as a config value or a one-line comment with the doc URL, so it's never looked up twice.

### Commands
- Keep output short: quiet/summary flags (`pnpm -s`, `-q`, `--silent`, `--oneline`, `--stat`, `-n 20`) and filters (`| tail -n 40`, `| grep -iE "error|fail"`).
- Narrowest check first: one test file or test name (`uv run --project training pytest training/tests/test_schema.py -q -k golden`, `pnpm vitest run packages/sqlgen/src/schema.test.ts`). Widen to the full suite only when the targeted check passes or the change is broad.
- Send long output (builds, training logs, full suites, eval runs) to a file and grep it: `… > /tmp/run.log 2>&1; grep -iE "error|loss|accuracy" /tmp/run.log | tail -n 30`.
- Poll Kaggle with `kaggle kernels status` at ≥ 5-minute intervals and print only the status line; never loop tightly.
- Don't re-run a command whose result was already clear.
- When a CLI and an MCP tool do the same job (e.g. `gh` vs a GitHub MCP server), use the CLI (`gh`, `kaggle`, `hf`, `wrangler`).

### Editing
- Edit only the lines that change; don't rewrite whole files for small changes.
- Don't create files nobody asked for (summaries, reports, extra docs/READMEs, examples, scratch scripts); files named in this spec count as asked for. Delete temp files you create.
- Add comments, docstrings, or logging only when asked or when essential.

### Replies
- Lead with the result. No preamble, no restating the request, no step-by-step narration.
- Reference code as `path:line` instead of pasting what's already in files. Show a snippet only when asked or when the snippet is the answer.
- Finish with at most 5 lines: what changed, how it was verified, what's still open.
- Explain only what isn't obvious. Match reasoning depth to the difficulty of the step.
- Skip task lists for short tasks; update them only at milestones.

### When stuck
- Same approach failed twice: stop. Report what you tried, the evidence, and your best hypothesis, then propose one different approach or ask.
- Don't guess repeatedly at APIs, flags, or config; look them up once.
- If you catch yourself re-reading the same files or cycling between fixes, stop and summarize.

### Subagents and parallel work
- Use a subagent only to keep bulk out of this conversation: wide multi-directory searches, verbose test/build runs, training-log analysis, full eval runs. Never for single-file lookups.
- Brief subagents precisely and ask for a short report (about 150 words plus `path:line` references), not raw output.
- Don't launch agent teams, workflows, or many parallel agents unless asked.

### Session hygiene
- If the user starts an unrelated task in a long session, suggest `/clear` in one line, then proceed.
- When asked for a handoff (or before a `/clear`), write `HANDOFF.md` (gitignored) in 40 lines or fewer: goal, current state, key files, decisions, failed approaches (one line each), verification commands, next step.

### Compact instructions
When compacting, keep: the goal, current milestone, decisions and constraints, files changed, unresolved errors (exact text), test and eval commands, latest run id with its metrics, GPU hours used this week, next steps. Drop: dead ends, file contents, passing test output, superseded plans.

## Repo map
- `training/`: Python 3.12 (uv), package `pocketsql` in `training/src/pocketsql/`: `data/` (download, convert, split), `synth/` (synthetic pairs), `train/`, `export/`, `evalx/` (scorer), `release/` (gate, upload). `configs/` holds train/export YAML; `data/` is gitignored except `data/cards/`; `runs/<id>/summary.json` is committed.
- `kaggle/`: kernel folders pushed with the Kaggle CLI (`kaggle/train/`).
- `packages/sqlgen/`: TypeScript schema serializer, prompt builder, SQL post-processing; shared by web and evals; npm-publishable.
- `evals/`: test sets, predictions, reports, and the Node generator for the ONNX artifact.
- `web/`: Vite + React + TS + Tailwind; Transformers.js v4 + DuckDB-WASM; PWA.
- `worker/`: Cloudflare Worker serving `web/dist` plus `/api/compare`.
- `.github/workflows/`: `ci.yml`, `artifact-eval.yml`, `e2e-real.yml`, `deploy.yml`, `smoke.yml`.
- `.claude/rules/`: path-scoped specs. `docs/ROADMAP.md`: milestones and acceptance criteria.

## Commands (create these scripts in M0; keep the names stable)
- Setup: `uv sync --project training` · `pnpm i`
- Data: `uv run --project training python -m pocketsql.data.prepare` · `uv run --project training python -m pocketsql.data.demo` · `uv run --project training python -m pocketsql.data.leakage [--from-hub]` · `uv run --project training python -m pocketsql.synth --n 200` (needs `GROQ_API_KEY`)
- Python checks: `uv run --project training ruff check -q` · `uv run --project training pytest -q`
- JS checks: `pnpm -s lint` · `pnpm -s typecheck` · `pnpm -s test` · `pnpm -s e2e`
- Kaggle: `kaggle kernels push -p kaggle/train` (needs approval) · `kaggle kernels status majedazar/pocketsql-train` · `kaggle kernels output majedazar/pocketsql-train -p training/runs/<run_id>`
- Evals: `pnpm eval:onnx --model <hf-repo>@<revision> --set own_test` · `uv run --project training python -m pocketsql.evalx.score evals/predictions/<file>.jsonl`
- Release: `uv run --project training python -m pocketsql.release.gate` → upload with `hf upload` (needs approval)
- Web: `pnpm dev` · `pnpm build` · `pnpm run deploy` (needs approval)

## Conventions
- Python 3.12 with type hints, `ruff format` + `ruff check`; no notebooks except the Kaggle kernel. TypeScript strict, ESM, Prettier defaults.
- Pin exact versions of Transformers.js, DuckDB-WASM, training libraries, and every Hub model/dataset revision.
- One change per training run so results stay attributable. New dependencies only when this spec names them or they replace substantial code.
- One branch per milestone task (e.g. `m1-data-prep`), Conventional Commits, PR to `main`; CI green before merge.

## Secrets & safety
- Kaggle and Hugging Face tokens live where their CLIs keep them (home directory, outside the repo); `GROQ_API_KEY` lives in `training/.env` (gitignored, read-denied) or the shell; Worker secrets (`GROQ_API_KEY`, `TURNSTILE_SECRET_KEY`, `SESSION_HMAC_SECRET`) via `wrangler secret put`, run by the user; CI secrets in GitHub Actions. Never read, print, or paste token files or values. If a secret shows up in a diff or output: stop and tell the user to rotate it.
- Kaggle pushes spend weekly GPU quota and Hub uploads publish artifacts: both need the user's approval (enforced in `.claude/settings.json`), as do `git push` and deploys.
- Everything under `web/` ships to browsers and is public.

## Human-only steps (stop, give exact instructions, wait)
- Create free accounts without a card: Kaggle (phone-verified for GPU), Hugging Face, Cloudflare, Groq. Install and authenticate the `kaggle` and `hf` CLIs; run `wrangler login`; add GitHub Actions secrets. Tell Claude your `<kaggle-username>` and `<hf-username>` (given: Kaggle `majedazar`, Hugging Face `MidlightDDK`).
- Download Spider manually if the scripted download is blocked.
- Verify every SQL in `own_test`; review 50 synthetic pairs; accept gated model licenses on the Hub if needed.
- Run the browser speed test on your own devices; record the demo video; approve the final README.

## Where the details live
- `.claude/rules/data.md` (data, synth, packages/sqlgen) · `training.md` (train, export, release, configs, kaggle) · `evals.md` (evals/**, evalx, .github/**) · `web.md` (web/**, worker/**). They load automatically when you read matching files. Before creating the first file in an area, read its rule file directly.
- `docs/ROADMAP.md`: milestones, acceptance criteria, M0 file templates, README outline.

## Milestone status (tick only when every acceptance box for that milestone passes)
- [x] M0 Scaffold + hello-world deploy + CLIs ready
- [x] M1 Data: Spider → DuckDB, serializer, splits
- [x] M2 Own test set, baselines, export spike
- [x] M3 Synthetic data + dataset release
- [x] M4 Train v1 on Kaggle
- [x] M5 Artifact eval, gate, model release
- [x] M6 Offline web app
- [x] M7 Cascade + launch

