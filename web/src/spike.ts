// M2 export spike: load the re-exported base model in the browser and time 3 queries.
import {
  AutoModelForCausalLM,
  AutoTokenizer,
  env,
  type ProgressInfo,
  type Tensor,
} from "@huggingface/transformers";
import { buildMessages } from "@pocketsql/sqlgen";
import schemas from "../../evals/sets/schemas.json";

// huggingface.co answers requests whose Referer is a *.workers.dev page with a
// 404 and no CORS headers, so model downloads go out without a referrer.
env.fetch = (input, init) =>
  fetch(input, { ...init, referrerPolicy: "no-referrer" });

const MODEL = "MidlightDDK/pocketsql-base-0.5b";
const REVISION = "cdb0fbdbb0af527488cdae1029a0c11af0da8a5d";
const QUESTIONS = [
  "How many customers are there?",
  "Which 3 artists have the most albums? Show the artist name and album count.",
  "What was the total revenue in each year? Order by year.",
];
// Extra keys reach the Jinja template; enable_thinking is not in the option types.
const TEMPLATE_OPTIONS = {
  add_generation_prompt: true,
  enable_thinking: false,
  return_dict: true,
} as const;

const $ = (id: string) => document.getElementById(id) as HTMLElement;
const status = (text: string) => {
  $("status").textContent = text;
};

async function hasWebGpu(): Promise<boolean> {
  const gpu = (navigator as { gpu?: { requestAdapter(): Promise<unknown> } })
    .gpu;
  return Boolean(gpu && (await gpu.requestAdapter().catch(() => null)));
}

async function main() {
  const forced = new URLSearchParams(location.search).get("device");
  const webgpu = forced !== "wasm" && (await hasWebGpu());
  const device = webgpu ? "webgpu" : "wasm";
  const dtype = webgpu ? "q4f16" : "q4";
  $("env").textContent =
    `Device: ${device} · dtype: ${dtype} · model: ${MODEL}@${REVISION}`;

  const files = new Map<string, { loaded: number; total: number }>();
  const onProgress = (p: ProgressInfo) => {
    if (p.status !== "progress") return;
    files.set(p.file, { loaded: p.loaded, total: p.total });
    let loaded = 0;
    let total = 0;
    for (const f of files.values()) {
      loaded += f.loaded;
      total += f.total;
    }
    ($("progress") as HTMLProgressElement).value = total ? loaded / total : 0;
    status(
      `Downloading ${(loaded / 2 ** 20).toFixed(0)} / ${(total / 2 ** 20).toFixed(0)} MB`,
    );
  };

  const t0 = performance.now();
  const tokenizer = await AutoTokenizer.from_pretrained(MODEL, {
    revision: REVISION,
  });
  const model = await AutoModelForCausalLM.from_pretrained(MODEL, {
    revision: REVISION,
    device,
    dtype,
    progress_callback: onProgress,
  });
  const loadMs = performance.now() - t0;
  ($("progress") as HTMLProgressElement).value = 1;
  status(`Loaded in ${(loadMs / 1000).toFixed(1)} s. Generating…`);

  const runs: { question: string; sql: string; ms: number; tokens: number }[] =
    [];
  for (const question of QUESTIONS) {
    const inputs = tokenizer.apply_chat_template(
      buildMessages(schemas.chinook, question),
      TEMPLATE_OPTIONS,
    ) as unknown as { input_ids: Tensor; attention_mask: Tensor };
    const start = performance.now();
    const output = (await model.generate({
      ...inputs,
      max_new_tokens: 256,
      do_sample: false,
    })) as Tensor;
    const ms = performance.now() - start;
    const promptLength = inputs.input_ids.dims[1] ?? 0;
    const total = output.dims[1] ?? 0;
    const [sql = ""] = tokenizer.batch_decode(
      output.slice(null, [promptLength, total]),
      {
        skip_special_tokens: true,
      },
    );
    runs.push({
      question,
      sql,
      ms: Math.round(ms),
      tokens: total - promptLength,
    });
    const block = document.createElement("div");
    const h = document.createElement("h3");
    h.textContent = question;
    const pre = document.createElement("pre");
    pre.textContent = `${sql}\n\n-- ${Math.round(ms)} ms, ${total - promptLength} tokens`;
    block.append(h, pre);
    $("results").append(block);
  }
  status(
    `Done. Load ${(loadMs / 1000).toFixed(1)} s; queries ${runs.map((r) => r.ms).join(" / ")} ms.`,
  );

  const report = {
    model: `${MODEL}@${REVISION}`,
    device,
    dtype,
    load_ms: Math.round(loadMs),
    runs,
    userAgent: navigator.userAgent,
  };
  const copy = $("copy") as HTMLButtonElement;
  copy.disabled = false;
  copy.onclick = () =>
    navigator.clipboard.writeText(JSON.stringify(report, null, 1));
}

main().catch((e: unknown) => {
  status(`Failed: ${e instanceof Error ? e.message : String(e)}`);
  console.error(e);
});
