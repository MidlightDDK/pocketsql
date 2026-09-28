import { formatEta, formatMB, formatMs } from "../format";
import { loadModel, useModel } from "../llm/store";
import { DOWNLOAD_MIB } from "../model";
import { useServiceWorkerActive } from "../pwa";

/** Download progress (MB, speed, ETA), then which backend the model runs on. */
export function ModelPanel() {
  const m = useModel();
  if (m.status === "idle") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
        <p>
          The model ({DOWNLOAD_MIB.q4f16}–{DOWNLOAD_MIB.q4} MB) downloads once,
          then answers offline. Data saver is on, so it waits for you.
        </p>
        <button
          type="button"
          className="btn-primary"
          onClick={() => void loadModel()}
        >
          Download the model
        </button>
      </div>
    );
  }
  if (m.status === "error") {
    return (
      <div
        role="alert"
        className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950"
      >
        <p className="font-medium">The model could not load.</p>
        <p className="mt-1 text-red-800 dark:text-red-300">{m.error}</p>
        <p className="mt-1">The examples below still work.</p>
      </div>
    );
  }
  if (m.status === "loading") {
    const fraction = m.total ? Math.min(1, m.loaded / m.total) : 0;
    const speed = m.bytesPerSec
      ? ` · ${(m.bytesPerSec / 2 ** 20).toFixed(1)} MB/s`
      : "";
    const eta =
      m.etaS !== null && m.etaS > 0 ? ` · about ${formatEta(m.etaS)} left` : "";
    return (
      <div className="rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
        <div className="flex flex-wrap justify-between gap-2">
          <span className="font-medium">
            {m.loaded >= m.total && m.total > 0
              ? "Starting the model…"
              : `Downloading the model (${m.device === "webgpu" ? "WebGPU" : "CPU"})`}
          </span>
          <span
            className="tabular-nums text-zinc-600 dark:text-zinc-400"
            data-testid="download-progress"
          >
            {formatMB(m.loaded)} / {formatMB(m.total)}
            {speed}
            {eta}
          </span>
        </div>
        <div
          className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
          role="progressbar"
          aria-label="Model download"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
        >
          <div
            className="h-full bg-teal-600 transition-[width] dark:bg-teal-400"
            style={{ width: `${fraction * 100}%` }}
          />
        </div>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Meanwhile, the examples below show answers this model wrote earlier.
        </p>
        {m.device === "wasm" ? <SlowerMode /> : null}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p
        className="text-sm text-zinc-600 dark:text-zinc-400"
        data-testid="model-ready"
      >
        Model ready on{" "}
        {m.device === "webgpu"
          ? "WebGPU"
          : m.device === "wasm"
            ? "the CPU (WASM)"
            : "a stub"}
        {m.loadMs ? ` · loaded in ${formatMs(m.loadMs)}` : ""}
      </p>
      {m.device === "wasm" ? <SlowerMode /> : null}
    </div>
  );
}

function SlowerMode() {
  return (
    <p className="mt-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
      Slower mode: this browser has no WebGPU, so the model runs on the CPU.
      Expect up to a minute per question; Chrome or Edge on a laptop with a GPU
      answers in seconds.
    </p>
  );
}

/** Shown once the model files and the app shell are both cached. */
export function OfflineBadge() {
  const m = useModel();
  const sw = useServiceWorkerActive();
  if (!(sw && m.status === "ready" && m.cached)) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-800 dark:bg-teal-950 dark:text-teal-200"
      title="The app and the model are cached: this page keeps working with Wi-Fi off."
    >
      <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true">
        <path
          d="M3 8.5l3 3 7-7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        />
      </svg>
      Offline ready
    </span>
  );
}
