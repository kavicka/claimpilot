import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run the real api (uvicorn) against its own database, claimpilot_e2e, seeded
// with claims as the worker would leave them; no models run. Redis and Postgres come from
// `make up` locally and from service containers in CI.
const ui = path.dirname(fileURLToPath(import.meta.url));
export const repoRoot = path.resolve(ui, "..");
const API_PORT = 4499;
const UI_PORT = 4498;

const inherited = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);

export const e2eEnv: Record<string, string> = {
  ...inherited,
  CLAIMPILOT_DATABASE_URL: "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_e2e",
  CLAIMPILOT_STORAGE_DIR: path.join(os.tmpdir(), "claimpilot-e2e"),
  CLAIMPILOT_ENVIRONMENT: "dev",
  CLAIMPILOT_DEMO_PASSWORD: "e2e-password",
  CLAIMPILOT_SESSION_SECRET: "e2e-session-secret",
  CLAIMPILOT_INTAKE_TOKEN: "e2e-intake-token",
  CLAIMPILOT_MCP_TOKEN: "e2e-service-token",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one database
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${UI_PORT}`,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `uv run --no-sync uvicorn claimpilot_api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: repoRoot,
      env: e2eEnv,
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: process.env.CI ? `pnpm next build && pnpm next start -p ${UI_PORT}` : `pnpm next dev -p ${UI_PORT}`,
      cwd: ui,
      env: { ...e2eEnv, CLAIMPILOT_API_URL: `http://127.0.0.1:${API_PORT}` },
      url: `http://localhost:${UI_PORT}/login`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
