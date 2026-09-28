import { DATASET_URL, KERNEL_URL, MODEL_CARD_URL, REPO_URL } from "../config";
import { MODEL_REVISION } from "../model";
import { Link } from "../router";

const STAGES: { title: string; body: string; link?: [string, string] }[] = [
  {
    title: "Data",
    body: "7,227 Spider pairs converted from SQLite to DuckDB, kept only when both engines return the same result, plus 591 synthetic pairs for the demo databases (one model writes them, two others must agree).",
    link: ["Dataset on the Hub", DATASET_URL],
  },
  {
    title: "Training",
    body: "LoRA (rank 16) on Qwen2.5-Coder-0.5B-Instruct, 2 epochs on one free Kaggle T4 GPU: 51 minutes.",
    link: ["Kaggle notebook", KERNEL_URL],
  },
  {
    title: "Export",
    body: "Merge the adapter and quantize to 4-bit ONNX: q4f16 for WebGPU (276 MB) and q4 for the CPU fallback (310 MB).",
  },
  {
    title: "Release gate",
    body: "Score the exact ONNX files. Ship only if they score no lower than the base model's export and the previous release. Run v1 failed; run v2 shipped.",
    link: ["Eval results", "/evals"],
  },
  {
    title: "Hugging Face Hub",
    body: `MidlightDDK/pocketsql-0.5b, pinned to revision ${MODEL_REVISION.slice(0, 7)}.`,
    link: ["Model card", MODEL_CARD_URL],
  },
  {
    title: "Your browser",
    body: "Transformers.js runs the model in a Web Worker (WebGPU, or WASM on the CPU). DuckDB-WASM runs the SQL. A service worker and the browser cache keep it all working offline.",
  },
];

const STEPS = [
  "The schema is written as one CREATE TABLE line per table, with up to 2 example values for short text columns: the same serializer as in training, tested byte for byte in Python and TypeScript.",
  "The prompt goes through the model's chat template, exactly as in training. Decoding is greedy, up to 256 new tokens, streamed to the page.",
  "The output is cleaned (code fences stripped, first statement kept) and checked with DuckDB's EXPLAIN.",
  "If DuckDB rejects it, the model tries once more with sampling (temperature 0.3). If that fails too, you see DuckDB's error.",
  "DuckDB-WASM runs the query on the database in your tab, and simple two-column results get a chart.",
];

export default function How() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">How it works</h1>
      <p className="mt-3 max-w-3xl text-zinc-600 dark:text-zinc-400">
        From public data to a model that runs offline in a browser tab, on free
        tiers only: Kaggle for the GPU, the Hugging Face Hub for weights and
        data, Cloudflare Workers for this site.
      </p>

      <ol className="mt-10 grid gap-4 md:grid-cols-3" aria-label="Pipeline">
        {STAGES.map((s, i) => (
          <li
            key={s.title}
            className="relative rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
          >
            <span className="text-xs font-medium text-teal-700 dark:text-teal-400">
              {String(i + 1).padStart(2, "0")}
            </span>
            <h2 className="mt-1 font-semibold">{s.title}</h2>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              {s.body}
            </p>
            {s.link ? (
              s.link[1].startsWith("/") ? (
                <Link
                  href={s.link[1]}
                  className="link mt-3 inline-block text-sm"
                >
                  {s.link[0]} →
                </Link>
              ) : (
                <a href={s.link[1]} className="link mt-3 inline-block text-sm">
                  {s.link[0]} →
                </a>
              )
            ) : null}
            {i < STAGES.length - 1 ? (
              <span
                aria-hidden="true"
                className="absolute -bottom-4 left-1/2 -translate-x-1/2 text-zinc-400 md:hidden"
              >
                ↓
              </span>
            ) : null}
          </li>
        ))}
      </ol>

      <section className="mt-12 max-w-3xl">
        <h2 className="text-xl font-semibold">What happens when you ask</h2>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          {STEPS.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        <p className="mt-6 text-sm">
          Code, tests, and training configs:{" "}
          <a href={REPO_URL} className="link">
            github.com/MidlightDDK/pocketsql
          </a>
        </p>
      </section>
    </div>
  );
}
