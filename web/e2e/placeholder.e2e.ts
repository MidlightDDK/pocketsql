import { expect, test } from "@playwright/test";

test("placeholder page renders", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("PocketSQL");
  await expect(
    page.getByRole("heading", { level: 1, name: "PocketSQL" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Source on GitHub" }),
  ).toBeVisible();
});
