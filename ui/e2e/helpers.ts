import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { e2eEnv, repoRoot } from "../playwright.config";

export const API = "http://127.0.0.1:4499";
export const PASSWORD = "e2e-password";

/** Three claims and one invoice, as the worker would leave them (tests/e2e/seed.py). */
export function seed() {
  execFileSync("uv", ["run", "--no-sync", "python", "tests/e2e/seed.py"], {
    cwd: repoRoot,
    env: e2eEnv as NodeJS.ProcessEnv,
    stdio: "pipe",
  });
}

export async function login(page: Page, username = "handler.demo", password = PASSWORD) {
  await page.goto("/login");
  await page.waitForLoadState("networkidle"); // typing before React hydrates is lost
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

export async function seriousViolations(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} → ${v.nodes.map((n) => `${n.target.join(" ")} ${n.html.slice(0, 120)} ${n.failureSummary ?? ""}`).join(" | ")}`);
}
