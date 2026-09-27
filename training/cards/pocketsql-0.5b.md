---
license: apache-2.0
base_model: Qwen/Qwen2.5-Coder-0.5B-Instruct
library_name: transformers.js
pipeline_tag: text-generation
language:
  - en
tags:
  - text-to-sql
  - duckdb
  - onnx
  - webgpu
  - transformers.js
datasets:
  - MidlightDDK/pocketsql-data
---

# PocketSQL 0.5B

A 0.5B-parameter model fine-tuned to turn plain-English questions into **DuckDB SQL** for a schema you give it. It is small enough to run entirely in a web browser with [Transformers.js](https://github.com/huggingface/transformers.js): 4-bit ONNX on WebGPU (q4f16) or WASM (q4). It powers [PocketSQL](https://github.com/MidlightDDK/pocketsql), a demo that keeps working with Wi-Fi off.

**Release v2** (training run v2, 2026-09-27). On 100 held-out questions over the app's demo databases, the shipped 4-bit model returns the correct result for **45%** (the base model's 4-bit export: 29%), and for **49%** of the 981 Spider-dev questions (base: 31%). It downloads once: 276 MiB for WebGPU, 310 MiB for the WASM fallback.

## Files

| File | Use | Size |
|---|---|---|
| `onnx/model_q4f16.onnx` | Browser, WebGPU (default) | 269 MiB |
| `onnx/model_q4.onnx` | Browser, WASM fallback; Node CPU | 303 MiB |
| `model.safetensors` | Merged fp16 PyTorch weights (reference) | 942 MiB |

`config.json` carries `transformers.js_config`, which picks the dtype per device (WebGPU → q4f16, WASM → q4). Tokenizer and generation files come from the base model. The 4-bit graphs are what the numbers below measure; the PyTorch weights are only there for context and further fine-tuning.

## Usage (Transformers.js 4.3.0)

```js
import { AutoModelForCausalLM, AutoTokenizer } from "@huggingface/transformers";

const repo = "MidlightDDK/pocketsql-0.5b";
const revision = "<commit sha>"; // pin a revision
const tokenizer = await AutoTokenizer.from_pretrained(repo, { revision });
const model = await AutoModelForCausalLM.from_pretrained(repo, {
  revision,
  device: "webgpu", // or "wasm"
  dtype: "q4f16", // "q4" on wasm
});

const schema =
  "CREATE TABLE penguins (species VARCHAR /* e.g. 'Adelie', 'Gentoo' */, island VARCHAR /* e.g. 'Biscoe', 'Dream' */, bill_length_mm DOUBLE, bill_depth_mm DOUBLE, flipper_length_mm BIGINT, body_mass_g BIGINT, sex VARCHAR /* e.g. 'male', 'female' */, year BIGINT);";
const messages = [
  { role: "system", content: "Write one DuckDB SQL query that answers the question. Output only SQL." },
  { role: "user", content: `${schema}\n\nQuestion: What is the average body mass of each species?` },
];
const inputs = tokenizer.apply_chat_template(messages, { add_generation_prompt: true, return_dict: true });
const output = await model.generate({ ...inputs, max_new_tokens: 256, do_sample: false });
const prompt = inputs.input_ids.dims[1];
const sql = output.slice(null, [prompt, output.dims[1]]);
console.log(tokenizer.batch_decode(sql, { skip_special_tokens: true })[0]);
```

## Prompt format

The base model's chat template with two messages:

- **system:** `Write one DuckDB SQL query that answers the question. Output only SQL.`
- **user:** the schema as compact DDL, one `CREATE TABLE t (col TYPE, …);` line per table, with up to 2 example values as `/* e.g. 'a', 'b' */` for text columns that have at most 20 distinct values; then a blank line and `Question: <question>`.

The model answers with one SQL statement ending in `;`. Use greedy decoding. The serializer that builds the schema text exists in Python (`pocketsql.data.schema`) and TypeScript (`@pocketsql/sqlgen`) and is tested to produce identical prompts.

## Training

- **Base:** [Qwen/Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct) @ `ea3f247`.
- **Data:** [MidlightDDK/pocketsql-data](https://huggingface.co/datasets/MidlightDDK/pocketsql-data) @ `b078ef1`: 7,818 pairs that fit in 1,024 tokens (7,227 from Spider's train and train-others splits, 591 synthetic pairs for the three demo databases; 149 longer pairs dropped). Validation: 858 Spider pairs from 16 held-out databases.
- **Method:** LoRA (r 16, alpha 32, dropout 0, all linear layers), 2 epochs (490 steps), learning rate 2e-4 cosine with 3% warmup, effective batch 32, fp16 mixed precision, loss on the SQL only, seed 42; TRL 1.14 + PEFT 0.21 + transformers 5.17. The adapter is merged into the base weights.
- **Export:** ONNX Runtime GenAI model builder 0.17: int4 `MatMulNBits`, block size 32, round-to-nearest; fp16 activations and KV cache in q4f16. The q4 graph replaces the quantized-embedding op with standard ops, because ONNX Runtime Web's WASM build lacks it.
- **Compute:** one Kaggle T4, 61 GPU minutes for this run (51 of them training). The project has used about 2 GPU hours in total, all on Kaggle's free tier.
- **History:** run v1 (Spider only) reached the same validation accuracy (59.9% vs 60.0%) but scored 20% on the demo-database test set, below the base model, so the release gate refused it. Adding the synthetic pairs was the only change in v2.

## Evaluation

Execution accuracy (EX): the generated SQL runs on DuckDB and must return the gold query's result (row order counts only when the gold query has a top-level `ORDER BY`; floats match within 1e-6). Greedy decoding, at most 256 new tokens, the same prompt for every model. ONNX rows are the exact files in this repo, run through Transformers.js 4.3.0 in Node (q4f16 on WebGPU, q4 on CPU); PyTorch rows are context.

- **own_test:** 100 verified questions over Chinook, Palmer penguins, and World Bank indicators (19 easy, 33 medium, 27 hard, 21 extra). Never trained on: synthetic questions close to a test question (token-Jaccard ≥ 0.9, or the same result as its gold query) were removed.
- **Spider-dev:** the 981 Spider dev pairs that survive conversion to DuckDB, 20 databases never seen in training; "100" is the seeded subset the slower baselines were run on.

| Model | Runtime | own_test EX | own_test valid SQL | Spider-dev 100 | Spider-dev 981 | Download |
|---|---|---|---|---|---|---|
| **PocketSQL 0.5B v2** | **ONNX q4f16, WebGPU** | **45%** | 83% | 53% | 49.3% | 276 MiB |
| | ONNX q4, CPU (WASM path) | 43% | 83% | 54% | | 310 MiB |
| | PyTorch, merged weights | 49% | 90% | | | 942 MiB |
| Qwen2.5-Coder-0.5B-Instruct (base) | ONNX q4f16, WebGPU | 29% | 54% | 32% | 30.9% | 276 MiB |
| | ONNX q4, CPU | 30% | 50% | | | 310 MiB |
| | PyTorch | 36% | 58% | 39% | | |
| gpt-oss-120b (reference) | Groq API | 77% | 95% | 73% | | none; ~$0.0001 per query |

own_test by difficulty (q4f16, this model vs base export): easy 84% vs 74%, medium 55% vs 33%, hard 26% vs 15%, extra 19% vs 0%. Of the 55 misses, 18 are valid SQL with a wrong result, 12 reference a column or table that does not exist, 11 pick the wrong column or table, 9 aggregate wrongly, 3 join wrongly, and 2 are not DuckDB syntax.

**Quantization.** On 50 seeded validation prompts, the 4-bit graphs return the same result as the merged PyTorch model on 31/50 (identical SQL on 19–20/50). EX there is 54% for q4f16 and q4 vs 60% for PyTorch; on own_test it is 45% and 43% vs 49%. So 4-bit weights cost about 4–6 points. A k-quant recipe recovered part of that on run v1 (same SQL result as PyTorch on 40/50 instead of 32/50, for 7 MiB more) and is the next change to try.

**Speed** (Node on the development PC, Windows 11 with an Intel integrated GPU; context, not a browser benchmark): q4f16 on WebGPU p50 0.6 s, p95 1.2 s per own_test question; q4 on CPU p50 3.4 s, p95 9.1 s.

## Limitations

- DuckDB dialect only; other engines may reject its date functions, `ILIKE`, or `QUALIFY`.
- Trained on Spider-style schemas plus synthetic questions for the three demo databases; unfamiliar domains, very wide schemas, and prompts over 1,024 tokens are weaker.
- It has no notion of what the data means beyond the schema text and example values: it can pick a plausible but wrong column, mishandle NULLs, or misread an ambiguous question. Check results before relying on them.
- Most hard and extra-hard questions (multi-step logic, window functions, careful NULL handling) still fail: 26% and 19% EX on own_test, against 62–63% for a 120B model.

## License and attribution

- Model: Apache-2.0, like the base model [Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct) (Qwen team).
- Training data: [MidlightDDK/pocketsql-data](https://huggingface.co/datasets/MidlightDDK/pocketsql-data), CC BY-SA 4.0, derived from [Spider](https://yale-lily.github.io/spider) (Yu et al., 2018) plus synthetic pairs generated with Apache-2.0 models (gpt-oss-120b, gpt-oss-20b, Qwen3.8-27B) through the Groq API.
- Demo databases used in the test set: Chinook (MIT), Palmer penguins (CC0 1.0), World Development Indicators (CC BY 4.0).
