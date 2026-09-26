const REPO_URL = "https://github.com/MidlightDDK/pocketsql";

export function App() {
  return (
    <main className="min-h-screen bg-white px-4 py-16 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto max-w-xl">
        <h1 className="text-4xl font-semibold tracking-tight">PocketSQL</h1>
        <p className="mt-4 text-lg text-zinc-600 dark:text-zinc-400">
          A small model I fine-tuned to turn plain-English questions into DuckDB
          SQL, running entirely in your browser, even offline.
        </p>
        <p className="mt-8 rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
          Work in progress: the live demo is coming soon.
        </p>
        <a
          className="mt-8 inline-block text-sm font-medium underline underline-offset-4"
          href={REPO_URL}
        >
          Source on GitHub
        </a>
      </div>
    </main>
  );
}
