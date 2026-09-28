import { lazy, Suspense } from "react";
import { REPO_URL } from "./config";
import { Home } from "./home/Home";
import { Link, usePath } from "./router";
import { OfflineBadge } from "./ui/ModelStatus";

const Evals = lazy(() => import("./evals/Evals"));
const How = lazy(() => import("./how/How"));

const NAV = [
  ["/", "Demo"],
  ["/evals", "Evals"],
  ["/how", "How it works"],
] as const;

export function App() {
  const path = usePath();
  return (
    <div className="min-h-screen bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="border-b border-zinc-200 dark:border-zinc-800">
        <nav
          className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3"
          aria-label="Main"
        >
          <Link href="/" className="font-semibold tracking-tight">
            PocketSQL
          </Link>
          <ul className="flex gap-4 text-sm">
            {NAV.map(([href, label]) => (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={path === href ? "page" : undefined}
                  className="text-zinc-600 hover:text-zinc-900 aria-[current=page]:font-medium aria-[current=page]:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 dark:aria-[current=page]:text-zinc-100"
                >
                  {label}
                </Link>
              </li>
            ))}
            <li>
              <a
                href={REPO_URL}
                className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              >
                GitHub
              </a>
            </li>
          </ul>
          <span className="ml-auto">
            <OfflineBadge />
          </span>
        </nav>
      </header>
      <main>
        <Suspense
          fallback={
            <p className="mx-auto max-w-6xl px-4 py-10 text-sm text-zinc-500">
              Loading…
            </p>
          }
        >
          {path === "/evals" ? <Evals /> : path === "/how" ? <How /> : <Home />}
        </Suspense>
      </main>
    </div>
  );
}
