// The real model (e2e-real.yml, or E2E_REAL=1 locally): load → go offline →
// reload → ask 3 questions → results render. A persistent profile keeps the
// model in the browser cache between runs (E2E_PROFILE, cached in CI).
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { chromium, expect, test } from "@playwright/test";
import { watchCsp } from "./csp";

test.skip(!process.env.E2E_REAL, "set E2E_REAL=1 to download the real model");

// Questions the released model answers correctly (own_test), one per database.
const QUESTIONS = [
  ["Music store", "How many customers are there?"],
  ["Penguins", "How many penguins are in the dataset?"],
  ["World Bank", "How many countries are in the database?"],
] as const;

test("works offline with the real model", async ({ baseURL }) => {
  test.setTimeout(30 * 60_000);
  const profile =
    process.env.E2E_PROFILE ?? join(tmpdir(), "pocketsql-e2e-profile");
  const context = await chromium.launchPersistentContext(profile, { baseURL });
  const page = context.pages()[0] ?? (await context.newPage());
  const violations = await watchCsp(page);

  // A cached profile may hold an old build's service worker: keep only the model.
  await page.goto("/");
  const cachedModel = await page.evaluate(async () => {
    for (const r of await navigator.serviceWorker.getRegistrations())
      await r.unregister();
    for (const key of await caches.keys())
      if (key !== "transformers-cache") await caches.delete(key);
    return caches.has("transformers-cache");
  });

  const start = Date.now();
  await page.goto("/");
  await expect(page.getByTestId("model-ready")).toBeVisible({
    timeout: 20 * 60_000,
  });
  const firstLoadS = (Date.now() - start) / 1000;
  await expect(page.getByText("Offline ready")).toBeVisible({
    timeout: 60_000,
  });
  const device = await page.getByTestId("model-ready").textContent();

  await context.setOffline(true);
  const reload = Date.now();
  await page.reload();
  await expect(page.getByTestId("model-ready")).toBeVisible({
    timeout: 10 * 60_000,
  });
  const offlineLoadS = (Date.now() - reload) / 1000;

  const answer = page.getByTestId("answer");
  const queryS: number[] = [];
  for (const [dataset, question] of QUESTIONS) {
    await page.getByRole("button", { name: dataset, exact: true }).click();
    await page.getByLabel(/Your question/).fill(question);
    const t = Date.now();
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByTestId("answer-origin")).toContainText(
      "Written by the model",
      {
        timeout: 10 * 60_000,
      },
    );
    queryS.push((Date.now() - t) / 1000);
    await expect(answer.getByRole("heading", { name: question })).toBeVisible();
    await expect(answer.getByRole("table")).toBeVisible();
  }
  expect(await violations()).toEqual([]);

  const report = {
    device,
    userAgent: await page.evaluate(() => navigator.userAgent),
    crossOriginIsolated: await page.evaluate(() => crossOriginIsolated),
    cached_model: cachedModel,
    first_load_s: firstLoadS,
    offline_load_s: offlineLoadS,
    query_s: queryS,
  };
  console.log(JSON.stringify(report));
  const out = join("test-results", "real-model.json");
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, `${JSON.stringify(report, null, 1)}\n`);
  await context.close();
});
