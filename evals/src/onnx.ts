import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import {
  AutoModelForCausalLM,
  AutoTokenizer,
  env,
  type Tensor,
} from "@huggingface/transformers";
import { buildMessages } from "@pocketsql/sqlgen";
import { EVALS, loadSchemas, loadSet, readJsonl } from "./sets.ts";

// Greedy ONNX predictions through Transformers.js in Node:
// `pnpm eval:onnx --model <hf-repo>@<revision>|<local dir> --name <model>
//   --set own_test --dtype q4f16 --device webgpu [--limit N]`
// writes evals/predictions/<name>__onnx-<dtype>-<device>__<set>.jsonl (resumable).
const { values } = parseArgs({
  options: {
    model: { type: "string" },
    name: { type: "string" },
    set: { type: "string", default: "own_test" },
    dtype: { type: "string", default: "q4f16" },
    device: { type: "string", default: "webgpu" },
    limit: { type: "string" },
  },
});
if (!values.model)
  throw new Error("--model <hf-repo>@<revision> or a local dir");
const MAX_NEW_TOKENS = 256;
// Extra keys reach the Jinja template; enable_thinking is not in the option types.
const TEMPLATE_OPTIONS = {
  add_generation_prompt: true,
  enable_thinking: false,
  return_dict: true,
} as const;

let id = values.model;
let revision: string | undefined;
if (existsSync(values.model)) {
  env.localModelPath = `${dirname(resolve(values.model))}/`;
  env.allowRemoteModels = false;
  id = basename(values.model);
} else {
  [id, revision] = values.model.split("@") as [string, string | undefined];
}
const name = values.name ?? basename(id).toLowerCase();
const runtime = `onnx-${values.dtype}-${values.device}`;
const out = join(
  EVALS,
  "predictions",
  `${name}__${runtime}__${values.set}.jsonl`,
);
const done = new Set(
  existsSync(out) ? readJsonl<{ id: string }>(out).map((p) => p.id) : [],
);
const limit = values.limit ? Number(values.limit) : undefined;
const items = loadSet(values.set)
  .slice(0, limit)
  .filter((i) => !done.has(i.id));
const schemas = loadSchemas();

const tokenizer = await AutoTokenizer.from_pretrained(id, { revision });
const model = await AutoModelForCausalLM.from_pretrained(id, {
  revision,
  dtype: values.dtype as "q4f16",
  device: values.device as "webgpu",
});
mkdirSync(dirname(out), { recursive: true });
for (const [n, item] of items.entries()) {
  const schema = schemas[item.db_id];
  if (schema === undefined) throw new Error(`no schema for ${item.db_id}`);
  const inputs = tokenizer.apply_chat_template(
    buildMessages(schema, item.question),
    TEMPLATE_OPTIONS,
  ) as unknown as { input_ids: Tensor; attention_mask: Tensor };
  const start = performance.now();
  const output = (await model.generate({
    ...inputs,
    max_new_tokens: MAX_NEW_TOKENS,
    do_sample: false,
  })) as Tensor;
  const latency = performance.now() - start;
  const promptLength = inputs.input_ids.dims[1] ?? 0;
  const total = output.dims[1] ?? 0;
  const generated = output.slice(null, [promptLength, total]);
  const [sql] = tokenizer.batch_decode(generated, {
    skip_special_tokens: true,
  });
  const row = {
    id: item.id,
    sql: sql ?? "",
    latency_ms: Math.round(latency * 10) / 10,
    tokens_out: total - promptLength,
  };
  appendFileSync(out, `${JSON.stringify(row)}\n`);
  if ((n + 1) % 10 === 0)
    console.log(`${n + 1}/${items.length} ${latency.toFixed(0)} ms`);
}
await model.dispose();
console.log(`wrote ${out}`);
