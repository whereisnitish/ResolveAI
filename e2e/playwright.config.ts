import { defineConfig, devices } from "@playwright/test";

/**
 * Browser E2E against a running stack (servers are started outside Playwright so the
 * same suite runs locally and in CI):
 *   E2E_BASE_URL    dashboard (Next.js)          default http://localhost:3101
 *   E2E_API_URL     Django (widget talks to it)  default http://localhost:8001
 *   E2E_WIDGET_URL  widget demo host page        default http://localhost:3002
 * The backend should run with CELERY_TASK_ALWAYS_EAGER=true and no LLM keys (mock AI),
 * which makes AI replies deterministic.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3101",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
