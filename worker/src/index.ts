export interface Env {
  ASSETS: Fetcher;
}

function json(body: unknown, status = 200, headers: HeadersInit = {}) {
  return Response.json(body, {
    status,
    headers: { "cache-control": "no-store", ...headers },
  });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (!pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (pathname !== "/api/health") return json({ error: "not_found" }, 404);
    if (request.method !== "GET") {
      return json({ error: "method_not_allowed" }, 405, { allow: "GET" });
    }
    return json({ status: "ok" });
  },
} satisfies ExportedHandler<Env>;
