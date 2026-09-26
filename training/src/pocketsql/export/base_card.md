---
license: apache-2.0
base_model: Qwen/Qwen2.5-Coder-0.5B-Instruct
library_name: transformers.js
pipeline_tag: text-generation
tags:
  - onnx
  - text-to-sql
  - pocketsql
---

# PocketSQL base (unmodified Qwen2.5-Coder-0.5B-Instruct, ONNX)

An unmodified ONNX re-export of [Qwen/Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct) at revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`. It is the export spike and the zero-shot baseline for [PocketSQL](https://github.com/MidlightDDK/pocketsql), which fine-tunes this model to write DuckDB SQL in the browser. It is **not** fine-tuned.

## Files

| Transformers.js dtype | File | Download (with tokenizer) | Use |
|---|---|---|---|
| q4f16 | `onnx/model_q4f16.onnx` | 276 MiB | WebGPU (default) |
| q4 | `onnx/model_q4.onnx` | 310 MiB | WASM fallback |

## How it was built

With the ONNX Runtime GenAI model builder (`onnxruntime-genai==0.17.0`), the same tool whose producer tag appears in the onnx-community Qwen ONNX builds: `-p int4 -e webgpu --extra_options block_size=32` (q4f16) and `-p int4 -e cpu --extra_options block_size=32` (q4). The KV-cache head dimension is then pinned to 64 so Transformers.js can size the empty cache, and `transformers.js_config` in `config.json` sets q4f16 on WebGPU and q4 on WASM. Source: `training/src/pocketsql/export/build.py` in the PocketSQL repo.

## Parity (greedy outputs vs PyTorch fp32, 20 prompts, Transformers.js 4.3.0 in Node)

| Export | Same text | Same DuckDB result |
|---|---|---|
| fp32 (not uploaded) | 20/20 | 20/20 |
| q4 | 4/20 | 13/20 |
| q4f16 | 4/20 | 13/20 |

Zero-shot execution accuracy is in `evals/reports/latest.json` in the PocketSQL repo.

## Usage

```js
import { AutoModelForCausalLM, AutoTokenizer } from "@huggingface/transformers";
const id = "MidlightDDK/pocketsql-base-0.5b";
const tokenizer = await AutoTokenizer.from_pretrained(id);
const model = await AutoModelForCausalLM.from_pretrained(id, { device: "webgpu", dtype: "q4f16" });
```

The prompt format (system message, compact schema DDL, `Question: …`) is described in the PocketSQL README.

## License

Apache-2.0, inherited from Qwen2.5-Coder-0.5B-Instruct.
