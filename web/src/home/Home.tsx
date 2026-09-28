import { useEffect, useRef, useState } from "react";
import { askBigModel, sameResult, useCompareAvailable } from "../compare";
import examples from "../data/examples.json";
import { type Dataset, DEMO_DATASETS } from "../datasets";
import { addUpload, getEngine, type Result, runSql } from "../db";
import { formatMs } from "../format";
import { useModel } from "../llm/store";
import { Link } from "../router";
import { Chart, chartSpec } from "../ui/Chart";
import { ModelPanel } from "../ui/ModelStatus";
import { ResultTable } from "../ui/ResultTable";
import { type Answer, askModel, runInto } from "./ask";

type Example = (typeof examples)[number];

const precomputed = (e: Example): Answer => ({
  question: e.question,
  datasetId: e.db_id,
  sql: e.sql,
  origin: "precomputed",
  result: {
    columns: e.columns,
    rows: e.rows as Result["rows"],
    rowCount: e.rows.length,
    ms: 0,
  },
});

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    addEventListener("online", update);
    addEventListener("offline", update);
    return () => {
      removeEventListener("online", update);
      removeEventListener("offline", update);
    };
  }, []);
  return online;
}

export function Home() {
  const model = useModel();
  const [datasets, setDatasets] = useState<Dataset[]>(DEMO_DATASETS);
  const [datasetId, setDatasetId] = useState(examples[0]?.db_id ?? "chinook");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(() =>
    examples[0] ? precomputed(examples[0]) : null,
  );
  const [draft, setDraft] = useState(answer?.sql ?? "");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const dataset = datasets.find((d) => d.id === datasetId) ?? DEMO_DATASETS[0];

  // DuckDB-WASM starts right away, so edited SQL runs without a wait.
  useEffect(() => {
    void getEngine().catch(() => {});
  }, []);

  function show(a: Answer) {
    setAnswer(a);
    setDraft(a.sql);
  }

  function pickExample(e: Example) {
    setDatasetId(e.db_id);
    setQuestion(e.question);
    show(precomputed(e));
  }

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    if (!dataset || !question.trim() || busy) return;
    setBusy(true);
    setStreaming("");
    try {
      show(await askModel(dataset, question.trim(), setStreaming));
    } catch (err) {
      show({
        question: question.trim(),
        datasetId: dataset.id,
        sql: "",
        origin: "model",
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setStreaming(null);
      setBusy(false);
    }
  }

  async function runDraft() {
    if (!answer || busy) return;
    setBusy(true);
    try {
      show(
        await runInto({
          ...answer,
          sql: draft,
          origin: "edited",
          retried: false,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setUploadError(null);
    try {
      const { id, table, schema } = await addUpload(file);
      setDatasets((ds) => [
        ...ds,
        {
          id,
          label: file.name,
          blurb: `Your file, loaded into DuckDB in this tab as table ${table}. Nothing leaves your device.`,
          schema,
          upload: true,
        },
      ]);
      setDatasetId(id);
      setAnswer(null);
      setQuestion("");
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    }
  }

  const ready = model.status === "ready";
  return (
    <div className="mx-auto max-w-6xl px-4 pb-24">
      <section className="py-10">
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
          Ask a database in plain English. The model runs in your browser.
        </h1>
        <p className="mt-4 max-w-3xl text-lg text-zinc-600 dark:text-zinc-400">
          PocketSQL is a 0.5B-parameter model I fine-tuned to write DuckDB SQL.
          It downloads once, then answers on your device, even with Wi-Fi off.
          On my 100-question test set it gets{" "}
          <Link href="/evals" className="link">
            45% right, up from 29% for the base model
          </Link>
          .
        </p>
      </section>

      <ModelPanel />

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          <fieldset>
            <legend className="text-sm font-medium">Database</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {datasets.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  aria-pressed={d.id === datasetId}
                  onClick={() => {
                    setDatasetId(d.id);
                    if (answer?.datasetId !== d.id) setAnswer(null);
                  }}
                  className="chip"
                >
                  {d.label}
                </button>
              ))}
              <label className="chip cursor-pointer">
                Upload CSV or Parquet
                <input
                  type="file"
                  accept=".csv,.parquet,text/csv"
                  className="sr-only"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void upload(file);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {uploadError ? (
              <p
                role="alert"
                className="mt-2 text-sm text-red-700 dark:text-red-400"
              >
                Could not load that file: {uploadError}
              </p>
            ) : null}
          </fieldset>

          <form onSubmit={ask} className="mt-6">
            <label htmlFor="question" className="text-sm font-medium">
              Your question about {dataset?.label}
            </label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <input
                id="question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. Which 5 countries had the largest population in 2023?"
                className="input flex-1"
                autoComplete="off"
              />
              <button
                type="submit"
                className="btn-primary"
                disabled={!ready || busy || !question.trim()}
              >
                {busy && streaming !== null ? "Writing SQL…" : "Ask"}
              </button>
            </div>
            {!ready ? (
              <p className="mt-2 text-sm text-zinc-500">
                You can ask once the model has loaded. The examples work now.
              </p>
            ) : null}
          </form>

          <section className="mt-6" aria-labelledby="examples-heading">
            <h2 id="examples-heading" className="text-sm font-medium">
              Examples{" "}
              <span className="font-normal text-zinc-500">
                (answered by this model earlier, so they show instantly)
              </span>
            </h2>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {examples.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    onClick={() => pickExample(e)}
                    className="h-full w-full rounded-md border border-zinc-200 p-3 text-left text-sm hover:border-teal-600 dark:border-zinc-800 dark:hover:border-teal-400"
                  >
                    <span className="block text-xs text-zinc-500">
                      {DEMO_DATASETS.find((d) => d.id === e.db_id)?.label}
                    </span>
                    {e.question}
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {streaming !== null ? (
            <section className="mt-8" aria-live="polite">
              <h2 className="text-sm font-medium">Writing SQL…</h2>
              <pre className="code mt-2">{streaming || " "}</pre>
            </section>
          ) : answer ? (
            <AnswerView
              answer={answer}
              draft={draft}
              setDraft={setDraft}
              onRun={() => void runDraft()}
              busy={busy}
              dataset={datasets.find((d) => d.id === answer.datasetId)}
            />
          ) : null}
        </div>

        <aside className="min-w-0">
          <details
            open
            className="rounded-lg border border-zinc-200 dark:border-zinc-800"
          >
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
              Schema the model sees
            </summary>
            <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                {dataset?.blurb}
              </p>
              <pre
                className="code mt-3 max-h-[28rem] text-xs"
                data-testid="schema"
              >
                {dataset?.schema}
              </pre>
              {dataset?.source ? (
                <p className="mt-3 text-xs text-zinc-500">
                  Source:{" "}
                  <a className="link" href={dataset.source.url}>
                    {dataset.source.name}
                  </a>{" "}
                  ({dataset.source.license})
                </p>
              ) : null}
            </div>
          </details>
        </aside>
      </div>
    </div>
  );
}

function AnswerView(props: {
  answer: Answer;
  draft: string;
  setDraft: (s: string) => void;
  onRun: () => void;
  busy: boolean;
  dataset: Dataset | undefined;
}) {
  const { answer, draft, setDraft, onRun, busy, dataset } = props;
  const model = useModel();
  const compareAvailable = useCompareAvailable();
  const spec = answer.result ? chartSpec(answer.result) : null;
  const origin =
    answer.origin === "precomputed"
      ? "Precomputed: written by this model earlier"
      : answer.origin === "edited"
        ? "Your SQL"
        : `Written by the model in ${formatMs(answer.genMs ?? 0)}${model.device === "webgpu" ? " on WebGPU" : model.device === "wasm" ? " on the CPU" : ""}${answer.retried ? " · second try after the first SQL failed" : ""}`;
  return (
    <section
      className="mt-8"
      aria-labelledby="answer-heading"
      data-testid="answer"
    >
      <h2 id="answer-heading" className="text-lg font-medium">
        {answer.question}
      </h2>
      <p className="mt-1 text-xs text-zinc-500" data-testid="answer-origin">
        {origin}
      </p>
      <label htmlFor="sql" className="sr-only">
        SQL
      </label>
      <textarea
        id="sql"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        rows={Math.min(12, Math.max(3, draft.split("\n").length + 1))}
        className="code mt-3 w-full resize-y"
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn"
          onClick={onRun}
          disabled={busy || !draft.trim()}
        >
          Run SQL
        </button>
        <span className="text-xs text-zinc-500">
          Edit the SQL and run it again. DuckDB runs in your browser.
        </span>
      </div>
      {answer.error ? (
        <div
          role="alert"
          className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950"
        >
          <p className="font-medium">
            {answer.origin === "model"
              ? "The model's SQL did not run."
              : "This SQL did not run."}
          </p>
          <p className="mt-1 font-mono text-xs break-words text-red-800 dark:text-red-300">
            {answer.error}
          </p>
          {answer.origin === "model" ? (
            <p className="mt-2">
              A 0.5B model gets about half of questions right. Try rephrasing,
              name the columns you want, or fix the SQL above.
            </p>
          ) : null}
        </div>
      ) : null}
      {answer.result ? (
        <div className="mt-4">
          {spec ? <Chart result={answer.result} spec={spec} /> : null}
          <div className="mt-4">
            <ResultTable result={answer.result} />
          </div>
        </div>
      ) : null}
      {dataset && !dataset.upload && compareAvailable ? (
        <ComparePanel
          key={`${answer.datasetId}:${answer.question}`}
          answer={answer}
        />
      ) : null}
    </section>
  );
}

type Compare =
  | { status: "idle" }
  | { status: "busy" }
  | { status: "error"; message: string }
  | {
      status: "done";
      sql: string;
      model: string;
      result?: Result;
      error?: string;
    };

function ComparePanel({ answer }: { answer: Answer }) {
  const online = useOnline();
  const [state, setState] = useState<Compare>({ status: "idle" });
  const turnstile = useRef<HTMLDivElement>(null);

  async function run() {
    if (!turnstile.current) return;
    setState({ status: "busy" });
    try {
      const big = await askBigModel(
        answer.datasetId,
        answer.question,
        turnstile.current,
      );
      try {
        const result = await runSql(answer.datasetId, big.sql);
        setState({ status: "done", sql: big.sql, model: big.model, result });
      } catch (err) {
        setState({
          status: "done",
          sql: big.sql,
          model: big.model,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const agree =
    state.status === "done" && state.result && answer.result
      ? sameResult(answer.result, state.result)
      : null;
  return (
    <div className="mt-8 border-t border-zinc-200 pt-6 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn"
          onClick={() => void run()}
          disabled={!online || state.status === "busy"}
        >
          {state.status === "busy"
            ? "Asking the big model…"
            : "Compare with a big model"}
        </button>
        <span className="text-xs text-zinc-500">
          {online
            ? "Sends this question and schema to gpt-oss-120b through my server (same prompt)."
            : "Needs a connection; everything else works offline."}
        </span>
      </div>
      <div ref={turnstile} className="mt-2" />
      {state.status === "error" ? (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">
          {state.message}
        </p>
      ) : null}
      {state.status === "done" ? (
        <div className="mt-4">
          <p className="text-sm font-medium" data-testid="agreement">
            {agree === null
              ? "Could not compare results."
              : agree
                ? "Same result as PocketSQL (ignoring row order and column names)."
                : "Different result from PocketSQL."}
          </p>
          <div className="mt-3 grid gap-4 md:grid-cols-2">
            <div className="min-w-0">
              <h3 className="text-xs font-medium text-zinc-500">
                PocketSQL (0.5B, in your browser)
              </h3>
              <pre className="code mt-1 text-xs">{answer.sql}</pre>
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-medium text-zinc-500">
                {state.model} (server)
              </h3>
              <pre className="code mt-1 text-xs">{state.sql}</pre>
              {state.error ? (
                <p className="mt-2 font-mono text-xs text-red-700 dark:text-red-400">
                  {state.error}
                </p>
              ) : state.result ? (
                <div className="mt-2">
                  <ResultTable result={state.result} />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
