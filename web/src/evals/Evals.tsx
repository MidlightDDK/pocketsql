// Tables straight from evals/reports/latest.json, the file the Python scorer writes.
import report from "../../../evals/reports/latest.json";
import failures from "../data/failures.json";
import { formatMs, pct } from "../format";
import { Link } from "../router";

interface Row {
  model: string;
  runtime: string;
  set: string;
  n: number;
  ex: number;
  valid_sql: number;
  latency_ms_p50: number | null;
  cost_per_query_usd: number;
  by_difficulty: Record<string, { n: number; ex: number }>;
  errors: Record<string, number>;
}
interface Cascade {
  set: string;
  rule: "valid" | "agree";
  n: number;
  answered_locally: number;
  local_precision: number;
  ex: number;
  big_ex: number;
  api_calls_per_100: number;
}
interface Browser {
  device: string;
  browser: string;
  backend: string;
  dtype: string;
  load_s: number;
  query_s: number[];
  measured: string;
}

const results = report.results as Row[];
const models = report.models as Record<
  string,
  { download_mib?: Record<string, number>; hf_repo?: string; revision?: string }
>;
const browser = ((report as { browser?: Browser[] }).browser ??
  []) as Browser[];
const cascade = ((report as { cascade?: Cascade[] }).cascade ??
  []) as Cascade[];
const SET_LABEL: Record<string, string> = {
  own_test: "Own test set",
  spider_dev_100: "Spider dev (100)",
};
const RULE_LABEL = {
  valid: "SQL runs and returns rows",
  agree: "…and a second sample agrees",
};

const SHIPPED = "pocketsql-0.5b-v2";
const BASE_EXPORT = "qwen2.5-coder-0.5b-export";
const BASE = "qwen2.5-coder-0.5b";
const BIG = "gpt-oss-120b";

function find(model: string, runtime: string, set: string): Row | undefined {
  return results.find(
    (r) => r.model === model && r.runtime === runtime && r.set === set,
  );
}

const LINES: { label: string; note: string; model: string; runtime: string }[] =
  [
    {
      label: "PocketSQL 0.5B",
      note: "ONNX q4f16, WebGPU (what the browser runs)",
      model: SHIPPED,
      runtime: "onnx-q4f16-webgpu",
    },
    {
      label: "PocketSQL 0.5B",
      note: "ONNX q4, CPU (the no-WebGPU fallback)",
      model: SHIPPED,
      runtime: "onnx-q4-cpu",
    },
    {
      label: "PocketSQL 0.5B",
      note: "PyTorch before quantization (context only)",
      model: SHIPPED,
      runtime: "torch-cpu",
    },
    {
      label: "Base model",
      note: "Qwen2.5-Coder-0.5B-Instruct, same ONNX q4f16 export",
      model: BASE_EXPORT,
      runtime: "onnx-q4f16-webgpu",
    },
    {
      label: "Base model",
      note: "same ONNX q4 export, CPU",
      model: BASE_EXPORT,
      runtime: "onnx-q4-cpu",
    },
    {
      label: "Base model",
      note: "PyTorch (context only)",
      model: BASE,
      runtime: "torch-cpu",
    },
    {
      label: "gpt-oss-120b",
      note: "117B parameters, through the Groq API",
      model: BIG,
      runtime: "groq",
    },
  ];

function size(model: string, runtime: string): string {
  const dtype = /q4f16/.test(runtime)
    ? "q4f16"
    : /q4/.test(runtime)
      ? "q4"
      : null;
  const mib = dtype ? models[model]?.download_mib?.[dtype] : undefined;
  return mib ? `${mib} MB` : "–";
}

function Table({ set, caption }: { set: string; caption: string }) {
  const rows = LINES.map((l) => ({
    ...l,
    row: find(l.model, l.runtime, set),
  })).filter((l) => l.row);
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="mb-2 text-left text-xs text-zinc-500">
          {caption}
        </caption>
        <thead className="border-b border-zinc-200 dark:border-zinc-800">
          <tr>
            <th scope="col" className="py-2 pr-4 font-medium">
              Model
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Execution accuracy
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Valid SQL
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Median latency
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Download
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Cost per query
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-900">
          {rows.map(({ label, note, model, runtime, row }) =>
            row ? (
              <tr
                key={`${model}-${runtime}`}
                className={
                  model === SHIPPED && runtime.includes("q4f16")
                    ? "bg-teal-50 dark:bg-teal-950/40"
                    : ""
                }
              >
                <td className="py-2 pr-4">
                  <span className="font-medium">{label}</span>
                  <span className="block text-xs text-zinc-500">{note}</span>
                </td>
                <td className="py-2 pr-4 text-right font-medium tabular-nums">
                  {pct(row.ex)}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {pct(row.valid_sql)}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {row.latency_ms_p50 === null
                    ? "–"
                    : formatMs(row.latency_ms_p50)}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {size(model, runtime)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {row.cost_per_query_usd
                    ? `$${row.cost_per_query_usd.toFixed(5)}`
                    : "$0"}
                </td>
              </tr>
            ) : null,
          )}
        </tbody>
      </table>
    </div>
  );
}

const DIFFICULTIES = ["easy", "medium", "hard", "extra"] as const;
const TAGS = [
  "wrong column or table",
  "hallucinated schema",
  "join error",
  "aggregation",
  "date/time functions",
  "dialect error",
  "formatting",
  "other",
];

export default function Evals() {
  const shipped = find(SHIPPED, "onnx-q4f16-webgpu", "own_test");
  const base = find(BASE_EXPORT, "onnx-q4f16-webgpu", "own_test");
  const big = find(BIG, "groq", "own_test");
  const devShipped = find(SHIPPED, "onnx-q4f16-webgpu", "spider_dev");
  const devBase = find(BASE_EXPORT, "onnx-q4f16-webgpu", "spider_dev");
  const devCascade = cascade.find(
    (c) => c.set === "spider_dev_100" && c.rule === "agree",
  );
  const byDiff = [
    ["PocketSQL q4f16", shipped],
    ["Base q4f16", base],
    ["gpt-oss-120b", big],
  ] as const;
  const errorRows = [
    ["PocketSQL q4f16", shipped],
    ["Base q4f16", base],
    ["gpt-oss-120b", big],
  ] as const;
  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Evals</h1>
      <p className="mt-3 max-w-3xl text-zinc-600 dark:text-zinc-400">
        Every number here comes from the exact quantized ONNX files the browser
        downloads, scored by one scorer that runs each predicted query and
        compares its result with the reference answer's result (execution
        accuracy). Updated {report.updated}.
      </p>

      {shipped && base && big ? (
        <dl className="mt-8 grid gap-4 sm:grid-cols-3">
          {[
            [
              "PocketSQL, in your browser",
              shipped.ex,
              `${size(SHIPPED, "q4f16")} download · $0 per query`,
            ],
            [
              "Base model, same export",
              base.ex,
              `${size(BASE_EXPORT, "q4f16")} download · $0 per query`,
            ],
            [
              "gpt-oss-120b, API",
              big.ex,
              `$${big.cost_per_query_usd.toFixed(5)} per query · needs a network`,
            ],
          ].map(([label, ex, sub]) => (
            <div
              key={label as string}
              className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
            >
              <dt className="text-sm text-zinc-600 dark:text-zinc-400">
                {label}
              </dt>
              <dd className="mt-1 text-3xl font-semibold tabular-nums">
                {pct(ex as number)}
              </dd>
              <dd className="mt-1 text-xs text-zinc-500">{sub}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p className="mt-3 text-xs text-zinc-500">
        Execution accuracy on my own test set: 100 questions over the three demo
        databases, each reference query checked by hand.
      </p>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">Own test set</h2>
        <Table
          set="own_test"
          caption="100 questions over Chinook, Palmer penguins, and World Bank data. Latency: median generation time per question (WebGPU and CPU rows measured in Node.js on a laptop; the API row includes the network)."
        />
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">Spider dev</h2>
        {devShipped && devBase ? (
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            On all {devShipped.n} Spider-dev questions that survived the SQLite
            → DuckDB conversion, PocketSQL (q4f16) scores {pct(devShipped.ex)}{" "}
            vs {pct(devBase.ex)} for the base model's export. Spider dev
            databases were never used in training.
          </p>
        ) : null}
        <Table
          set="spider_dev_100"
          caption="A fixed random 100-question subset of Spider dev, where the API model was also run."
        />
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">By difficulty</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="mb-2 text-left text-xs text-zinc-500">
              Own test set, execution accuracy (questions per level in
              brackets).
            </caption>
            <thead className="border-b border-zinc-200 dark:border-zinc-800">
              <tr>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Model
                </th>
                {DIFFICULTIES.map((d) => (
                  <th
                    key={d}
                    scope="col"
                    className="py-2 pr-4 text-right font-medium capitalize"
                  >
                    {d} ({shipped?.by_difficulty[d]?.n ?? 0})
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-900">
              {byDiff.map(([label, row]) =>
                row ? (
                  <tr key={label}>
                    <td className="py-2 pr-4">{label}</td>
                    {DIFFICULTIES.map((d) => (
                      <td key={d} className="py-2 pr-4 text-right tabular-nums">
                        {row.by_difficulty[d]
                          ? pct(row.by_difficulty[d].ex)
                          : "–"}
                      </td>
                    ))}
                  </tr>
                ) : null,
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">Local first, API when unsure</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          A cascade: PocketSQL answers every question first, for free, and the
          question goes to gpt-oss-120b only when the local answer looks wrong:
          its SQL fails to run or returns nothing, or (second rule) a second
          sample at temperature 0.3 returns a different result. The same model
          is tier 0 of the cascade in{" "}
          <a
            className="link"
            href="https://github.com/MidlightDDK/browser-analyst"
          >
            Browser Analyst
          </a>
          .
        </p>
        {cascade.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <caption className="mb-2 text-left text-xs text-zinc-500">
                Execution accuracy of the local answers kept, of the whole
                cascade, and of the API model on every question.
              </caption>
              <thead className="border-b border-zinc-200 dark:border-zinc-800">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Set
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Keep the local answer if
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Answered locally
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Local answers right
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Cascade
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    API alone
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    API calls per 100
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-900">
                {cascade.map((c) => (
                  <tr key={`${c.set}-${c.rule}`}>
                    <td className="py-2 pr-4">{SET_LABEL[c.set] ?? c.set}</td>
                    <td className="py-2 pr-4">{RULE_LABEL[c.rule]}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {pct(c.answered_locally)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {pct(c.local_precision)}
                    </td>
                    <td className="py-2 pr-4 text-right font-medium tabular-nums">
                      {pct(c.ex)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {pct(c.big_ex)}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {c.api_calls_per_100}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <p className="mt-3 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          On Spider dev the cascade beats the API model alone while making{" "}
          {devCascade?.api_calls_per_100 ?? "–"} calls per 100 questions. On the
          demo databases most of PocketSQL's wrong answers are valid SQL that
          returns the wrong rows, which these checks cannot see, so the cascade
          trades accuracy for fewer calls.
        </p>
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">Speed in real browsers</h2>
        {browser.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <caption className="mb-2 text-left text-xs text-zinc-500">
                Model load with its files already cached, then time from Ask to
                result for three questions, one per demo database; the first, on
                Chinook's 11 tables, is the slowest (longest prompt).
              </caption>
              <thead className="border-b border-zinc-200 dark:border-zinc-800">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Device
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Browser
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Backend
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Load
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    Per question
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-900">
                {browser.map((b) => (
                  <tr key={`${b.device}-${b.backend}`}>
                    <td className="py-2 pr-4">{b.device}</td>
                    <td className="py-2 pr-4">{b.browser}</td>
                    <td className="py-2 pr-4">
                      {b.backend} ({b.dtype})
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {b.load_s.toFixed(0)} s
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {Math.min(...b.query_s).toFixed(1)}–
                      {Math.max(...b.query_s).toFixed(1)} s
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm text-zinc-500">Not measured yet.</p>
        )}
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold">How the models fail</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Wrong answers on the own test set, tagged automatically. Fine-tuning
          mostly removed invented tables and columns ("hallucinated schema").
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="border-b border-zinc-200 dark:border-zinc-800">
              <tr>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Error
                </th>
                {errorRows.map(([label]) => (
                  <th
                    key={label}
                    scope="col"
                    className="py-2 pr-4 text-right font-medium"
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-900">
              {TAGS.filter((t) => errorRows.some(([, r]) => r?.errors[t])).map(
                (t) => (
                  <tr key={t}>
                    <td className="py-2 pr-4 capitalize">{t}</td>
                    {errorRows.map(([label, r]) => (
                      <td
                        key={label}
                        className="py-2 pr-4 text-right tabular-nums"
                      >
                        {r?.errors[t] ?? 0}
                      </td>
                    ))}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
        <div className="mt-6 space-y-4">
          {failures.map((f) => (
            <details
              key={f.id}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800"
            >
              <summary className="cursor-pointer px-4 py-3 text-sm">
                <span className="mr-2 rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">
                  {f.tag}
                </span>
                {f.question}
              </summary>
              <div className="grid gap-3 border-t border-zinc-200 p-4 text-xs md:grid-cols-2 dark:border-zinc-800">
                <div className="min-w-0">
                  <h3 className="font-medium text-zinc-500">PocketSQL wrote</h3>
                  <pre className="code mt-1 text-xs">
                    {f.sql || "(nothing)"}
                  </pre>
                  {f.error ? (
                    <p className="mt-1 font-mono break-words text-red-700 dark:text-red-400">
                      {f.error}
                    </p>
                  ) : null}
                </div>
                <div className="min-w-0">
                  <h3 className="font-medium text-zinc-500">Reference</h3>
                  <pre className="code mt-1 text-xs">{f.gold_sql}</pre>
                </div>
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="mt-12 max-w-3xl">
        <h2 className="text-xl font-semibold">Method</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>
            Every model gets the same prompt: the schema as one CREATE TABLE
            line per table (with up to 2 example values for short text columns),
            then the question. Decoding is greedy, up to 256 new tokens.
          </li>
          <li>
            Execution accuracy: the predicted query's result must equal the
            reference result, ignoring row order unless the reference has ORDER
            BY, with a 1e-6 float tolerance.
          </li>
          <li>
            The test sets were never used for training or for generating
            synthetic data; a leakage check runs in CI.
          </li>
          <li>
            Release gate: a model ships only if it scores no lower than the base
            model's export in the same runtime and than the previous release.
            Run v1 scored 20% on the own test set and was refused; run v2 is the
            release.
          </li>
          <li>
            The PyTorch rows show what quantization to 4 bits costs: 49% → 45%
            (q4f16) and 43% (q4) on the own test set.
          </li>
        </ul>
        <p className="mt-4 text-sm">
          <Link href="/how" className="link">
            How the model was built →
          </Link>
        </p>
      </section>
    </div>
  );
}
