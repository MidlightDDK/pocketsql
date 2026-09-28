import { handleCompare } from "./compare";
import type { Env } from "./env";
import { HttpError, json, log } from "./http";
import { handleSession } from "./session";

export type { Env };

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (!pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      if (pathname === "/api/health") {
        if (request.method !== "GET") {
          throw new HttpError(405, "method_not_allowed", { allow: "GET" });
        }
        // `compare`: the secrets /api/session and /api/compare need are set.
        const compare = Boolean(
          env.TURNSTILE_SECRET_KEY &&
            env.SESSION_HMAC_SECRET &&
            (env.GROQ_API_KEY || env.AI),
        );
        return json({ status: "ok", compare });
      }
      if (pathname === "/api/session") return await handleSession(request, env);
      if (pathname === "/api/compare") return await handleCompare(request, env);
      throw new HttpError(404, "not_found");
    } catch (err) {
      if (err instanceof HttpError) {
        return json({ reason: err.reason }, err.status, err.headers);
      }
      log({ route: pathname, status: 500 });
      return json({ reason: "internal" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
