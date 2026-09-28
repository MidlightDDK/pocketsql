// Daily check of the live site (smoke.yml, E2E_BASE_URL): the first paint shows
// a precomputed answer, another example opens instantly, its SQL runs in
// DuckDB-WASM, /api/health answers, and the pinned model is still on the Hub.
// The stub generator keeps the 276 MB model from downloading.
import { expect, test } from "@playwright/test";
import { MODEL_REPO, MODEL_REVISION } from "../src/model";
import { watchCsp } from "./csp";

test.skip(!process.env.E2E_BASE_URL, "runs against the live site");

test("live: a precomputed example, its SQL in DuckDB, health, and the model", async ({
  page,
  request,
}) => {
  const violations = await watchCsp(page);
  await page.goto("/?generator=stub");
  await expect(page).toHaveTitle("PocketSQL");
  const answer = page.getByTestId("answer");
  const origin = page.getByTestId("answer-origin");
  await expect(origin).toContainText("Precomputed");
  await expect(answer.getByRole("cell", { name: "USA" })).toBeVisible();

  await page
    .getByRole("button", { name: /total revenue in each year/ })
    .click();
  await expect(answer.getByRole("figure")).toBeVisible();
  await page.getByRole("button", { name: "Run SQL" }).click();
  await expect(origin).toHaveText("Your SQL");
  await expect(answer.getByRole("cell", { name: "2021" })).toBeVisible();

  const health = await request.get("/api/health");
  expect(health.ok()).toBe(true);
  expect(await health.json()).toMatchObject({ status: "ok" });
  const config = await request.head(
    `https://huggingface.co/${MODEL_REPO}/resolve/${MODEL_REVISION}/config.json`,
  );
  expect(config.ok()).toBe(true);
  expect(await violations()).toEqual([]);
});
