import { describe, expect, it, vi } from "vitest";
import { handleCompare, type Provider } from "./compare";
import worker, { type Env } from "./index";
import { hasSession, signSession } from "./session";

const ORIGIN = "https://pocket-sql.test";
const SECRET = "test-hmac-secret";
const allow = {
  limit: async () => ({ success: true }),
} as unknown as RateLimit;
const deny = {
  limit: async () => ({ success: false }),
} as unknown as RateLimit;

const baseEnv = {
  ASSETS: { fetch: async () => new Response("the app") },
  RL_COMPARE: allow,
  RL_SESSION: allow,
  SESSION_HMAC_SECRET: SECRET,
  TURNSTILE_SECRET_KEY: "turnstile-secret",
} as unknown as Env;

type WorkerRequest = Parameters<typeof worker.fetch>[0];

const call = (path: string, init?: RequestInit, env = baseEnv) =>
  worker.fetch(new Request(`${ORIGIN}${path}`, init) as WorkerRequest, env);

async function cookie(now = Date.now()) {
  return `ps_session=${(await signSession(SECRET, now)).value}`;
}

async function compareRequest(
  body: unknown,
  headers: Record<string, string> = {},
) {
  return new Request(`${ORIGIN}/api/compare`, {
    method: "POST",
    headers: {
      origin: ORIGIN,
      "content-type": "application/json",
      cookie: await cookie(),
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

const fixed = (text: string): Provider => ({
  id: "fake",
  configured: () => true,
  complete: async () => text,
});

describe("worker", () => {
  it("reports health", async () => {
    const res = await call("/api/health");
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ status: "ok", compare: false });
    const env = { ...baseEnv, AI: {} } as unknown as Env;
    const ready = await call("/api/health", undefined, env);
    expect(await ready.json()).toEqual({ status: "ok", compare: true });
  });

  it("returns 404 for unknown API routes", async () => {
    expect((await call("/api/nope")).status).toBe(404);
  });

  it("serves everything else from static assets", async () => {
    expect(await (await call("/evals")).text()).toBe("the app");
  });

  it("allows only POST on /api/compare and /api/session", async () => {
    expect((await call("/api/compare")).status).toBe(405);
    expect((await call("/api/session")).status).toBe(405);
  });
});

describe("session", () => {
  it("accepts its own cookie until it expires", async () => {
    const req = (c: string) => new Request(ORIGIN, { headers: { cookie: c } });
    expect(await hasSession(req(await cookie()), baseEnv)).toBe(true);
    const old = await cookie(Date.now() - 31 * 60_000);
    expect(await hasSession(req(old), baseEnv)).toBe(false);
    expect(await hasSession(req("ps_session=1.abc"), baseEnv)).toBe(false);
  });

  it("rejects cross-origin requests and bad Turnstile tokens", async () => {
    const post = (origin: string) =>
      call("/api/session", {
        method: "POST",
        headers: { origin },
        body: JSON.stringify({ turnstileToken: "x" }),
      });
    expect((await post("https://evil.test")).status).toBe(403);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ success: false }));
    const res = await post(ORIGIN);
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ reason: "turnstile" });
    fetchMock.mockResolvedValue(Response.json({ success: true }));
    const ok = await post(ORIGIN);
    expect(ok.status).toBe(200);
    expect(ok.headers.get("set-cookie")).toMatch(
      /^ps_session=\d+\.[\w-]+; .*HttpOnly; Secure/,
    );
    fetchMock.mockRestore();
  });
});

describe("compare", () => {
  it("sends the PocketSQL prompt and returns cleaned SQL", async () => {
    const complete = vi.fn(
      async () => "```sql\nSELECT count(*) FROM penguins;\n```",
    );
    const res = await handleCompare(
      await compareRequest({ schemaId: "penguins", question: "How many?" }),
      baseEnv,
      [{ id: "fake", configured: () => true, complete }],
    );
    expect(await res.json()).toMatchObject({
      sql: "SELECT count(*) FROM penguins;",
      model: "gpt-oss-120b",
      provider: "fake",
    });
    const [messages] = complete.mock.calls[0] as unknown as [
      { content: string }[],
    ];
    expect(messages[1]?.content).toMatch(
      /^CREATE TABLE penguins \(.*\n\nQuestion: How many\?$/s,
    );
  });

  it("falls back to the next provider", async () => {
    const failing: Provider = {
      id: "down",
      configured: () => true,
      complete: async () => {
        throw new Error("503");
      },
    };
    const res = await handleCompare(
      await compareRequest({ schemaId: "chinook", question: "Artists?" }),
      baseEnv,
      [failing, fixed("SELECT 1")],
    );
    expect(await res.json()).toMatchObject({
      sql: "SELECT 1;",
      provider: "fake",
    });
  });

  it("validates input, session, and rate limit", async () => {
    const run = async (req: Request, env = baseEnv) => {
      try {
        await handleCompare(req, env, [fixed("SELECT 1")]);
        return 200;
      } catch (err) {
        return (err as { status: number }).status;
      }
    };
    expect(
      await run(await compareRequest({ schemaId: "spider", question: "q" })),
    ).toBe(400);
    expect(
      await run(
        await compareRequest({
          schemaId: "penguins",
          question: "x".repeat(501),
        }),
      ),
    ).toBe(400);
    expect(
      await run(
        await compareRequest(
          { schemaId: "penguins", question: "q" },
          { cookie: "" },
        ),
      ),
    ).toBe(401);
    expect(
      await run(await compareRequest({ schemaId: "penguins", question: "q" }), {
        ...baseEnv,
        RL_COMPARE: deny,
      }),
    ).toBe(429);
    expect(
      await run(await compareRequest({ schemaId: "penguins", question: "q" }), {
        ...baseEnv,
        SESSION_HMAC_SECRET: undefined,
      }),
    ).toBe(503);
  });
});
