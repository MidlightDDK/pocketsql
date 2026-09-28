/** The subset of the Workers AI binding /api/compare uses. */
export interface AiBinding {
  run(model: string, inputs: Record<string, unknown>): Promise<unknown>;
}

export interface Env {
  ASSETS: Fetcher;
  AI?: AiBinding;
  RL_COMPARE: RateLimit;
  RL_SESSION: RateLimit;
  GROQ_API_KEY?: string;
  TURNSTILE_SECRET_KEY?: string;
  SESSION_HMAC_SECRET?: string;
}
