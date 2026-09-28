import { defineConfig, devices } from "@playwright/test";

const port = 4173;
// E2E_BASE_URL points the suite at a deployed site instead of a local server.
const remote = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "e2e",
  // `*.e2e.ts` keeps these files out of vitest's default include pattern.
  testMatch: "**/*.e2e.ts",
  forbidOnly: !!process.env.CI,
  // DuckDB-WASM (~30 MB) comes from jsDelivr on a cold browser profile.
  expect: { timeout: 30_000 },
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: remote ?? `http://localhost:${port}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // The production build with the production headers (vite.config.ts preview),
  // so the CSP and the service worker are the real ones.
  webServer: remote
    ? undefined
    : {
        command: `pnpm exec vite preview --port ${port} --strictPort`,
        url: `http://localhost:${port}`,
        reuseExistingServer: !process.env.CI,
      },
});
