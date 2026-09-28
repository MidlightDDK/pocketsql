// The app with the stub generator (?generator=stub): no model download, real
// DuckDB-WASM, real service worker, production CSP.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { watchCsp } from "./csp";

const schemas: Record<string, string> = JSON.parse(
  readFileSync(
    new URL("../../evals/sets/schemas.json", import.meta.url),
    "utf8",
  ),
);
const REVENUE =
  "What are the 5 billing countries with the most revenue? Show the country and revenue, highest first.";

test("examples show instantly, questions run through DuckDB, zero CSP violations", async ({
  page,
}) => {
  const violations = await watchCsp(page);
  await page.goto("/?generator=stub");
  await expect(page).toHaveTitle("PocketSQL");

  // A precomputed answer is on screen before anything loads.
  const answer = page.getByTestId("answer");
  await expect(answer.getByRole("heading", { name: REVENUE })).toBeVisible();
  await expect(answer.getByRole("cell", { name: "USA" })).toBeVisible();
  await expect(page.getByTestId("answer-origin")).toContainText("Precomputed");

  // A line chart for revenue by year.
  await page
    .getByRole("button", { name: /total revenue in each year/ })
    .click();
  await expect(answer.getByRole("figure")).toBeVisible();

  // Ask: the stub returns the example's SQL, which DuckDB runs on chinook.duckdb.
  await page.getByRole("button", { name: "Music store", exact: true }).click();
  await expect(page.getByTestId("model-ready")).toBeVisible();
  await page.getByLabel(/Your question/).fill(REVENUE);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByTestId("answer-origin")).toContainText(
    "Written by the model",
  );
  await expect(answer.getByRole("cell", { name: "Canada" })).toBeVisible();

  // Invalid SQL fails EXPLAIN, so the second sample is used.
  await page.getByLabel(/Your question/).fill("please retry");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByTestId("answer-origin")).toContainText("second try");
  await expect(answer.getByRole("cell", { name: "retried" })).toBeVisible();

  // Edited SQL runs on the selected database.
  await page.getByRole("button", { name: "Penguins", exact: true }).click();
  await page.getByLabel(/Your question/).fill("How many penguins?");
  await page.getByRole("button", { name: "Ask" }).click();
  await page
    .getByLabel("SQL", { exact: true })
    .fill("SELECT count(*) AS n FROM penguins;");
  await page.getByRole("button", { name: "Run SQL" }).click();
  await expect(page.getByTestId("answer-origin")).toHaveText("Your SQL");
  await expect(answer.getByRole("cell", { name: "344" })).toBeVisible();

  // DuckDB errors are shown, not swallowed.
  await page
    .getByLabel("SQL", { exact: true })
    .fill("SELECT nope FROM penguins;");
  await page.getByRole("button", { name: "Run SQL" }).click();
  await expect(answer.getByRole("alert")).toContainText("nope");

  expect(await violations()).toEqual([]);
});

test("the in-browser schema reader matches training's serializer", async ({
  page,
}) => {
  await page.goto("/?generator=stub");
  await page.waitForFunction(() => "__pocketsql" in window);
  for (const id of ["chinook", "penguins", "world_bank"]) {
    const text = await page.evaluate(
      (db) =>
        (
          window as unknown as {
            __pocketsql: { schemaText(id: string): Promise<string> };
          }
        ).__pocketsql.schemaText(db),
      id,
    );
    expect(text).toBe(schemas[id]);
  }
});

test("a CSV upload becomes a table with a prompt schema", async ({ page }) => {
  await page.goto("/?generator=stub");
  await page.getByText("Upload CSV or Parquet").setInputFiles({
    name: "My Pets.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("name,kind,age\nrex,dog,3\ntom,cat,5\nfido,dog,1\n"),
  });
  await expect(page.getByTestId("schema")).toHaveText(
    "CREATE TABLE my_pets (name VARCHAR /* e.g. 'fido', 'rex' */, kind VARCHAR /* e.g. 'dog', 'cat' */, age BIGINT);",
  );
});

test("evals and how pages render from the committed report", async ({
  page,
}) => {
  const violations = await watchCsp(page);
  await page.goto("/?generator=stub");
  await page.getByRole("link", { name: "Evals" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Evals" }),
  ).toBeVisible();
  await expect(page.getByText("45%").first()).toBeVisible();
  await page.getByRole("link", { name: "How it works" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "How it works" }),
  ).toBeVisible();
  expect(await violations()).toEqual([]);
});

test("the app shell and SQL keep working offline", async ({
  page,
  context,
}) => {
  await page.goto("/?generator=stub");
  await page.waitForFunction(async () => {
    const reg = await navigator.serviceWorker.ready;
    return reg.active?.state === "activated";
  });
  await context.setOffline(true);
  await page.reload();
  await page.getByRole("button", { name: "Penguins", exact: true }).click();
  await page
    .getByRole("button", { name: /average body mass of each species/ })
    .click();
  await page
    .getByLabel("SQL", { exact: true })
    .fill(
      "SELECT island, count(*) AS n FROM penguins GROUP BY island ORDER BY n DESC;",
    );
  await page.getByRole("button", { name: "Run SQL" }).click();
  await expect(
    page.getByTestId("answer").getByRole("cell", { name: "Biscoe" }),
  ).toBeVisible();
});
