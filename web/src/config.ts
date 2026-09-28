// Public values only: everything under web/ ships to browsers.

export const REPO_URL = "https://github.com/MidlightDDK/pocketsql";
export const MODEL_CARD_URL =
  "https://huggingface.co/MidlightDDK/pocketsql-0.5b";
export const DATASET_URL =
  "https://huggingface.co/datasets/MidlightDDK/pocketsql-data";
export const KERNEL_URL =
  "https://www.kaggle.com/code/majedazar/pocketsql-train";

const local = ["localhost", "127.0.0.1"].includes(location.hostname);

/**
 * Turnstile site key (public by design). The production widget (managed mode,
 * created with `wrangler turnstile widget create`) allows only
 * pocket-sql.azar-majed7.workers.dev. Local dev uses Cloudflare's always-pass
 * test key, paired with the test secret in worker/.dev.vars
 * (https://developers.cloudflare.com/turnstile/troubleshooting/testing/).
 */
export const TURNSTILE_SITE_KEY = local
  ? "1x00000000000000000000AA"
  : "0x4AAAAAAFF7enAXCj9pC4Pu";
