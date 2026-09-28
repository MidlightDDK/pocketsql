// The model's lifecycle, shared by every page: loading continues while the
// visitor browses /evals or /how.
import type { ChatMessage } from "@pocketsql/sqlgen";
import { useSyncExternalStore } from "react";
import examples from "../data/examples.json";
import { DOWNLOAD_MIB } from "../model";
import type { Device, Dtype, FromWorker, ToWorker } from "./protocol";

export interface ModelState {
  status: "idle" | "loading" | "ready" | "error";
  /** "stub" is the canned generator the CI end-to-end tests use (?generator=stub). */
  device: Device | "stub" | null;
  dtype: Dtype | null;
  loaded: number;
  total: number;
  bytesPerSec: number | null;
  etaS: number | null;
  loadMs: number | null;
  /** The model files are in the browser cache (so it loads offline). */
  cached: boolean;
  error: string | null;
}

export interface Generation {
  text: string;
  ms: number;
  tokens: number;
}

let state: ModelState = {
  status: "idle",
  device: null,
  dtype: null,
  loaded: 0,
  total: 0,
  bytesPerSec: null,
  etaS: null,
  loadMs: null,
  cached: false,
  error: null,
};
const listeners = new Set<() => void>();
function set(patch: Partial<ModelState>) {
  state = { ...state, ...patch };
  for (const l of listeners) l();
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export const useModel = () => useSyncExternalStore(subscribe, () => state);
export const modelState = () => state;

const params = new URLSearchParams(location.search);
export const STUB = params.get("generator") === "stub";

async function hasWebGpu(): Promise<boolean> {
  const gpu = (navigator as { gpu?: { requestAdapter(): Promise<unknown> } })
    .gpu;
  return Boolean(gpu && (await gpu.requestAdapter().catch(() => null)));
}

let worker: Worker | null = null;
let nextId = 0;
const pending = new Map<
  number,
  {
    resolve: (g: Generation) => void;
    reject: (e: Error) => void;
    onText?: (t: string) => void;
  }
>();

/** Download speed over the last few seconds of progress events. */
const samples: [number, number][] = [];
const files = new Map<string, { loaded: number; total: number }>();

function onProgress(file: string, fileLoaded: number, fileTotal: number) {
  files.set(file, { loaded: fileLoaded, total: fileTotal });
  let sum = 0;
  let known = 0;
  for (const f of files.values()) {
    sum += f.loaded;
    known += f.total;
  }
  const now = performance.now();
  samples.push([now, sum]);
  while (samples.length > 2 && now - (samples[0]?.[0] ?? now) > 4000)
    samples.shift();
  const [t0, b0] = samples[0] ?? [now, sum];
  const bytesPerSec = now - t0 > 500 ? ((sum - b0) / (now - t0)) * 1000 : null;
  const expected = state.dtype ? DOWNLOAD_MIB[state.dtype] * 2 ** 20 : 0;
  const total = Math.max(known, expected, sum);
  set({
    loaded: sum,
    total,
    bytesPerSec,
    etaS: bytesPerSec ? (total - sum) / bytesPerSec : null,
  });
}

function onMessage(e: MessageEvent<FromWorker>) {
  const m = e.data;
  if (m.type === "progress") onProgress(m.file, m.loaded, m.total);
  else if (m.type === "ready")
    set({
      status: "ready",
      loadMs: m.loadMs,
      cached: m.cached,
      loaded: state.total,
      etaS: 0,
    });
  else if (m.type === "text") pending.get(m.id)?.onText?.(m.text);
  else if (m.type === "done") {
    pending.get(m.id)?.resolve(m);
    pending.delete(m.id);
  } else if (m.id === undefined) set({ status: "error", error: m.message });
  else {
    pending.get(m.id)?.reject(new Error(m.message));
    pending.delete(m.id);
  }
}

/** Starts the download (once). WebGPU gets q4f16; everything else WASM q4. */
export async function loadModel(): Promise<void> {
  if (state.status === "loading" || state.status === "ready") return;
  if (STUB) {
    set({ status: "loading", device: "stub", dtype: "q4f16", total: 1 });
    setTimeout(
      () => set({ status: "ready", loaded: 1, loadMs: 0, cached: true }),
      300,
    );
    return;
  }
  const webgpu = params.get("device") !== "wasm" && (await hasWebGpu());
  const device: Device = webgpu ? "webgpu" : "wasm";
  const dtype: Dtype = webgpu ? "q4f16" : "q4";
  set({ status: "loading", device, dtype, error: null });
  worker ??= new Worker(new URL("./worker.ts", import.meta.url), {
    type: "module",
  });
  worker.onmessage = onMessage;
  worker.onerror = (e) =>
    set({ status: "error", error: e.message || "The model worker crashed" });
  worker.postMessage({ type: "load", device, dtype } satisfies ToWorker);
}

function stubGenerate(messages: ChatMessage[], sample: boolean): Generation {
  const question = (messages.at(-1)?.content ?? "").split("Question: ").at(-1);
  const example = examples.find((x) => x.question === question);
  let text = example?.sql ?? "SELECT 42 AS answer;";
  // "retry" exercises the invalid-SQL path: bad greedy SQL, valid second sample.
  if (question?.includes("retry"))
    text = sample ? "SELECT 'retried' AS answer;" : "SELECT nope FROM nowhere;";
  return { text, ms: 1, tokens: 1 };
}

export function generate(
  messages: ChatMessage[],
  sample: boolean,
  onText?: (text: string) => void,
): Promise<Generation> {
  if (STUB) return Promise.resolve(stubGenerate(messages, sample));
  if (!worker || state.status !== "ready")
    return Promise.reject(new Error("The model is not loaded yet"));
  const id = nextId++;
  const w = worker;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject, onText });
    w.postMessage({
      type: "generate",
      id,
      messages,
      sample,
    } satisfies ToWorker);
  });
}
