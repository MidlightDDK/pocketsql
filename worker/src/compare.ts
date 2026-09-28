// POST /api/compare {schemaId, question} → one large-model call with the prompt
// PocketSQL gets. gpt-oss-120b through Groq (the evals' API baseline, with the
// parameters of training/src/pocketsql/evalx/predict_groq.py), falling back to
// the same model on Workers AI when Groq has no key or fails.
import { buildMessages, type ChatMessage, cleanSql } from "@pocketsql/sqlgen";
import { chinook, penguins, world_bank } from "../../evals/sets/schemas.json";
import type { Env } from "./env";
import {
  HttpError,
  json,
  log,
  rateLimit,
  readJson,
  requireMethod,
  requireSameOrigin,
} from "./http";
import { hasSession } from "./session";

export const SCHEMAS: Record<string, string> = {
  chinook,
  penguins,
  world_bank,
};
export const MAX_QUESTION_CHARS = 500;
const TIMEOUT_MS = 25_000;
export const MODEL = "gpt-oss-120b";

// https://console.groq.com/docs/model/openai/gpt-oss-120b
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODEL = "openai/gpt-oss-120b";
// https://developers.cloudflare.com/workers-ai/models/gpt-oss-120b/
const WORKERS_AI_MODEL = "@cf/openai/gpt-oss-120b";

export interface Provider {
  id: string;
  configured(env: Env): boolean;
  complete(
    messages: ChatMessage[],
    env: Env,
    signal: AbortSignal,
  ): Promise<string>;
}

/** OpenAI-shaped (`choices[0].message.content`) or legacy (`response`) replies. */
function replyText(out: unknown): string {
  const o = (out ?? {}) as {
    choices?: { message?: { content?: unknown } }[];
    response?: unknown;
  };
  const content = o.choices?.[0]?.message?.content ?? o.response;
  return typeof content === "string" ? content : "";
}

export const PROVIDERS: Provider[] = [
  {
    id: "groq",
    configured: (env) => Boolean(env.GROQ_API_KEY),
    async complete(messages, env, signal) {
      const res = await fetch(GROQ_URL, {
        method: "POST",
        signal,
        headers: {
          authorization: `Bearer ${env.GROQ_API_KEY}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: GROQ_MODEL,
          messages,
          temperature: 0,
          reasoning_effort: "low",
          max_completion_tokens: 4096,
        }),
      });
      if (!res.ok) throw new Error(`groq ${res.status}`);
      return replyText(await res.json());
    },
  },
  {
    id: "workers-ai",
    configured: (env) => Boolean(env.AI),
    async complete(messages, env) {
      if (!env.AI) throw new Error("no AI binding");
      return replyText(
        await env.AI.run(WORKERS_AI_MODEL, {
          messages,
          temperature: 0,
          reasoning: { effort: "low" },
          max_tokens: 4096,
        }),
      );
    },
  },
];

function withTimeout<T>(run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const ctrl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      ctrl.abort();
      reject(new Error("timeout"));
    }, TIMEOUT_MS);
  });
  return Promise.race([run(ctrl.signal), timeout]).finally(() =>
    clearTimeout(timer),
  );
}

export async function handleCompare(
  request: Request,
  env: Env,
  providers = PROVIDERS,
): Promise<Response> {
  requireMethod(request, "POST");
  requireSameOrigin(request);
  const { schemaId, question } = await readJson(request, 4 * 1024);
  const schema = typeof schemaId === "string" ? SCHEMAS[schemaId] : undefined;
  if (
    !schema ||
    typeof question !== "string" ||
    !question.trim() ||
    question.length > MAX_QUESTION_CHARS
  ) {
    throw new HttpError(400, "invalid");
  }
  if (!env.SESSION_HMAC_SECRET) throw new HttpError(503, "unavailable");
  if (!(await hasSession(request, env))) throw new HttpError(401, "session");
  await rateLimit(env.RL_COMPARE, request);
  const messages = buildMessages(schema, question);
  for (const provider of providers) {
    if (!provider.configured(env)) continue;
    const start = Date.now();
    try {
      const sql = cleanSql(
        await withTimeout((signal) => provider.complete(messages, env, signal)),
      );
      if (!sql) throw new Error("empty reply");
      const ms = Date.now() - start;
      log({
        route: "compare",
        provider: provider.id,
        status: 200,
        latencyMs: ms,
      });
      return json({ sql, model: MODEL, provider: provider.id, ms });
    } catch (err) {
      const status = err instanceof Error ? err.message : "error";
      log({
        route: "compare",
        provider: provider.id,
        status: status.slice(0, 60),
      });
    }
  }
  throw new HttpError(502, "upstream");
}
