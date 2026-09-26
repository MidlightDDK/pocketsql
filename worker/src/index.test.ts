import { describe, expect, it } from "vitest";
import worker, { type Env } from "./index";

const env = {
  ASSETS: { fetch: async () => new Response("placeholder page") },
} as unknown as Env;

const call = (path: string, init?: RequestInit) =>
  worker.fetch(new Request(`https://pocket-sql.test${path}`, init), env);

describe("worker", () => {
  it("reports health", async () => {
    const res = await call("/api/health");
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ status: "ok" });
  });

  it("allows only GET on /api/health", async () => {
    const res = await call("/api/health", { method: "POST" });
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("GET");
  });

  it("returns 404 for unknown API routes", async () => {
    expect((await call("/api/compare")).status).toBe(404);
  });

  it("serves everything else from static assets", async () => {
    expect(await (await call("/")).text()).toBe("placeholder page");
  });
});
