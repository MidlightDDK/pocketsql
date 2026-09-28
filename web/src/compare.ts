// "Compare with a big model": one server-side call to a large model with the same
// prompt, behind a Turnstile-backed session cookie (worker/src/session.ts).
import { useEffect, useState } from "react";
import { TURNSTILE_SITE_KEY } from "./config";
import type { Result } from "./db";

export interface BigAnswer {
  sql: string;
  model: string;
  ms: number;
}

// https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/
const SCRIPT =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface Turnstile {
  render(
    el: HTMLElement,
    opts: {
      sitekey: string;
      appearance: "interaction-only";
      callback: (token: string) => void;
      "error-callback": () => void;
    },
  ): string;
  remove(id: string): void;
}

let script: Promise<Turnstile> | null = null;
function loadTurnstile(): Promise<Turnstile> {
  script ??= new Promise<Turnstile>((resolve, reject) => {
    const el = document.createElement("script");
    el.src = SCRIPT;
    const w = window as { turnstile?: Turnstile };
    el.onload = () =>
      w.turnstile
        ? resolve(w.turnstile)
        : reject(new Error("Turnstile did not load"));
    el.onerror = () => reject(new Error("Turnstile did not load"));
    document.head.append(el);
  }).catch((err: unknown) => {
    script = null;
    throw err;
  });
  return script;
}

async function turnstileToken(container: HTMLElement): Promise<string> {
  if (!TURNSTILE_SITE_KEY)
    throw new Error("Comparison is not set up on this site");
  const ts = await loadTurnstile();
  const sitekey = TURNSTILE_SITE_KEY;
  return new Promise((resolve, reject) => {
    const id = ts.render(container, {
      sitekey,
      appearance: "interaction-only",
      callback: (token) => {
        resolve(token);
        setTimeout(() => ts.remove(id));
      },
      "error-callback": () => {
        reject(new Error("The bot check failed; try again"));
        setTimeout(() => ts.remove(id));
      },
    });
  });
}

const REASONS: Record<string, string> = {
  rate_limit: "Too many comparisons from your network; wait a minute.",
  unavailable: "The big model is not available right now.",
  upstream: "The big model did not answer; try again.",
};

async function post(schemaId: string, question: string) {
  return fetch("/api/compare", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ schemaId, question }),
  });
}

/** Asks the big model; runs the bot check first when there is no session yet. */
export async function askBigModel(
  schemaId: string,
  question: string,
  turnstileContainer: HTMLElement,
): Promise<BigAnswer> {
  let res = await post(schemaId, question);
  if (res.status === 401) {
    const token = await turnstileToken(turnstileContainer);
    const session = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ turnstileToken: token }),
    });
    if (!session.ok) {
      const { reason = "" } = (await session.json().catch(() => ({}))) as {
        reason?: string;
      };
      throw new Error(REASONS[reason] ?? "The bot check failed; try again.");
    }
    res = await post(schemaId, question);
  }
  const body = (await res.json().catch(() => ({}))) as Partial<BigAnswer> & {
    reason?: string;
  };
  if (!res.ok || typeof body.sql !== "string")
    throw new Error(
      REASONS[body.reason ?? ""] ??
        `The comparison failed (HTTP ${res.status}).`,
    );
  return { sql: body.sql, model: body.model ?? "big model", ms: body.ms ?? 0 };
}

const norm = (v: unknown) =>
  typeof v === "number" ? Number(v.toPrecision(6)) : v;

/** Same rows in any order, ignoring column names (like the eval scorer without ORDER BY). */
export function sameResult(a: Result, b: Result): boolean {
  if (a.rowCount !== b.rowCount || a.columns.length !== b.columns.length)
    return false;
  const key = (r: Result) =>
    r.rows
      .map((row) => JSON.stringify(row.map(norm)))
      .sort()
      .join("\n");
  return key(a) === key(b);
}

let available: Promise<boolean> | null = null;

/** True once /api/health reports the Worker secrets comparison needs. */
export function useCompareAvailable(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    available ??= fetch("/api/health")
      .then((r) => r.json() as Promise<{ compare?: boolean }>)
      .then((h) => h.compare === true && Boolean(TURNSTILE_SITE_KEY))
      .catch(() => {
        available = null; // offline or failed: ask again next time
        return false;
      });
    let live = true;
    void available.then((v) => {
      if (live) setOk(v);
    });
    return () => {
      live = false;
    };
  }, []);
  return ok;
}
