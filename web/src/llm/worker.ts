// Runs the model off the main thread: greedy decoding, max 256 new tokens, and an
// optional second sample at temperature 0.3 (the retry after invalid SQL).
import {
  AutoModelForCausalLM,
  AutoTokenizer,
  env,
  type PreTrainedModel,
  type PreTrainedTokenizer,
  type ProgressInfo,
  type Tensor,
  TextStreamer,
} from "@huggingface/transformers";
import type { ChatMessage } from "@pocketsql/sqlgen";
import { MODEL_REPO, MODEL_REVISION } from "../model";
import type { Device, Dtype, FromWorker, ToWorker } from "./protocol";

const RESOLVE = `https://huggingface.co/${MODEL_REPO}/resolve/`;
const PINNED = `${RESOLVE}${MODEL_REVISION}/`;

// Every Hub request goes to the pinned revision and is answered from the cache
// when the file is there: Transformers.js 4.3.0 checks the tokenizer files on
// `main` whatever the revision (get_tokenizer_files), which would need the
// network offline. A pinned revision never changes, so cache-first is safe.
// huggingface.co answers requests whose Referer is a *.workers.dev page with a
// 404 and no CORS headers, so model downloads go out without a referrer.
env.fetch = async (input, init) => {
  let url = input instanceof Request ? input.url : String(input);
  if (url.startsWith(`${RESOLVE}main/`))
    url = PINNED + url.slice(`${RESOLVE}main/`.length);
  if (url.startsWith(PINNED)) {
    const hit = await caches
      .open(env.cacheKey)
      .then((c) => c.match(url))
      .catch(() => undefined);
    if (hit) return hit;
  }
  return fetch(url, { ...init, referrerPolicy: "no-referrer" });
};

const MAX_NEW_TOKENS = 256;
const RETRY_TEMPERATURE = 0.3;
// Extra keys reach the Jinja template; enable_thinking is not in the option types.
const TEMPLATE_OPTIONS = {
  add_generation_prompt: true,
  enable_thinking: false,
  return_dict: true,
} as const;

const post = (m: FromWorker) => self.postMessage(m);

let loaded: { tokenizer: PreTrainedTokenizer; model: PreTrainedModel } | null =
  null;

async function load(device: Device, dtype: Dtype) {
  const start = performance.now();
  const progress_callback = (p: ProgressInfo) => {
    if (p.status === "progress")
      post({
        type: "progress",
        file: p.file,
        loaded: p.loaded,
        total: p.total,
      });
  };
  const tokenizer = await AutoTokenizer.from_pretrained(MODEL_REPO, {
    revision: MODEL_REVISION,
    progress_callback,
  });
  const model = await AutoModelForCausalLM.from_pretrained(MODEL_REPO, {
    revision: MODEL_REVISION,
    device,
    dtype,
    progress_callback,
  });
  loaded = { tokenizer, model };
  // One token of warm-up compiles the WebGPU shaders before the first question.
  await run([{ role: "user", content: "SELECT" }], false, 1);
  const loadMs = performance.now() - start;
  post({ type: "ready", loadMs, cached: await cached(dtype) });
}

/**
 * Whether the pinned model files are in Transformers.js's Cache Storage, so the
 * next load works offline. (ModelRegistry.is_cached looks up tokenizer_config.json
 * on `main`, not the pinned revision, so it needs the network.)
 */
async function cached(dtype: Dtype): Promise<boolean> {
  try {
    const cache = await caches.open(env.cacheKey);
    const base = `https://huggingface.co/${MODEL_REPO}/resolve/${MODEL_REVISION}/`;
    const files = [
      "config.json",
      "tokenizer.json",
      "tokenizer_config.json",
      `onnx/model_${dtype}.onnx`,
    ];
    const hits = await Promise.all(files.map((f) => cache.match(base + f)));
    return hits.every(Boolean);
  } catch {
    return false;
  }
}

async function run(
  messages: ChatMessage[],
  sample: boolean,
  maxNewTokens = MAX_NEW_TOKENS,
  onText?: (text: string) => void,
) {
  if (!loaded) throw new Error("The model is not loaded yet");
  const { tokenizer, model } = loaded;
  const inputs = tokenizer.apply_chat_template(
    messages,
    TEMPLATE_OPTIONS,
  ) as unknown as { input_ids: Tensor; attention_mask: Tensor };
  let text = "";
  const streamer = onText
    ? new TextStreamer(tokenizer, {
        skip_prompt: true,
        skip_special_tokens: true,
        callback_function: (piece: string) => {
          text += piece;
          onText(text);
        },
      })
    : undefined;
  const start = performance.now();
  const output = (await model.generate({
    ...inputs,
    max_new_tokens: maxNewTokens,
    do_sample: sample,
    ...(sample ? { temperature: RETRY_TEMPERATURE } : {}),
    streamer,
  })) as Tensor;
  const ms = performance.now() - start;
  const promptLength = inputs.input_ids.dims[1] ?? 0;
  const total = output.dims[1] ?? 0;
  const [decoded = ""] = tokenizer.batch_decode(
    output.slice(null, [promptLength, total]),
    { skip_special_tokens: true },
  );
  return { text: decoded, ms, tokens: total - promptLength };
}

self.addEventListener("message", async (e: MessageEvent<ToWorker>) => {
  const msg = e.data;
  try {
    if (msg.type === "load") await load(msg.device, msg.dtype);
    else {
      const out = await run(msg.messages, msg.sample, MAX_NEW_TOKENS, (text) =>
        post({ type: "text", id: msg.id, text }),
      );
      post({ type: "done", id: msg.id, ...out });
    }
  } catch (err) {
    post({
      type: "error",
      id: msg.type === "generate" ? msg.id : undefined,
      message: err instanceof Error ? err.message : String(err),
    });
  }
});
