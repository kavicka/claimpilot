import { type Page, expect, test } from "@playwright/test";

import { login, seed, seriousViolations } from "./helpers";

const REF = "FA-2026-900001";

// One invoice in the standard queue: line 2 costs more than ordered, line 3 has a wrong VAT amount.
test.beforeEach(() => seed());

async function openInvoices(page: Page) {
  await page.getByRole("link", { name: "Invoices" }).click();
  await expect(page.getByRole("heading", { name: "Invoices", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /Standard/ }).click();
}

async function openInvoice(page: Page) {
  await openInvoices(page);
  await page.getByRole("row", { name: new RegExp(REF) }).click();
  await expect(page.getByRole("heading", { name: REF })).toBeVisible();
}

test("the invoice queue lists the invoice with its supplier, total, findings and rule", async ({ page }) => {
  await login(page);
  await openInvoices(page);
  const row = page.getByRole("row", { name: new RegExp(REF) });
  await expect(row).toContainText("BioFlora s.r.o.");
  await expect(row).toContainText("260104417");
  await expect(row).toContainText("€74.69");
  await expect(row).toContainText("I7");
  await expect(row).toContainText("In review");
  await expect(page.getByRole("tab", { name: /Standard/ })).toContainText("1");
});

test("the line with the price difference and the wrong VAT cell are flagged with their reasons", async ({ page }) => {
  await login(page);
  await openInvoice(page);
  const lines = page.getByRole("table", { name: "Invoice lines" });
  await expect(lines.getByRole("button", { name: "Line 2, 1 problem" })).toBeVisible();
  await expect(lines.getByRole("list", { name: "Problems on Line 2" })).toContainText(
    "Price differs from the order: 4.0800 invoiced, 4.00 ordered",
  );
  await expect(lines.getByRole("list", { name: "Problems on Line 3" })).toContainText("VAT: Line VAT does not match the rate (expected 0.75)");
  await expect(lines.getByRole("list", { name: "Problems on Line 1" })).toHaveCount(0);
  await page.getByRole("tab", { name: /Checks/ }).click();
  await expect(page.getByText("4.0800 invoiced, 4.00 ordered")).toBeVisible();
  await page.getByRole("button", { name: "Line 2", exact: true }).click();
  await expect(lines).toBeVisible();
});

test("clicking a line or a cell marks its box on the page; hovering a line outlines it", async ({ page }) => {
  await login(page);
  await openInvoice(page);
  const pageBox = page.locator('[data-page="1"]');
  await page.getByRole("button", { name: "Line 1", exact: true }).click();
  await expect(pageBox.locator('[data-mark="select"]')).toContainText("Line 1");
  await page.getByRole("button", { name: "Line 2, 1 problem" }).hover();
  await expect(pageBox.locator('[data-mark="hover"]')).toHaveCount(1);
  await page.getByRole("button", { name: /^Unit price, Line 2: 4,08/ }).click();
  await expect(pageBox.locator('[data-mark="select"]')).toContainText("lines[2].unit_price");
  await page.getByRole("tab", { name: /Header/ }).click();
  await page.getByRole("button", { name: "Invoice number", exact: true }).click();
  await expect(pageBox.locator('[data-mark="select"]')).toContainText("invoice_number");
});

test("a corrected cell blocks approval until the invoice is reassessed", async ({ page }) => {
  await login(page);
  await openInvoice(page);
  await page.getByRole("button", { name: /^Qty, Line 2: 5/ }).click();
  await page.getByRole("button", { name: "Correct Qty, Line 2" }).click();
  const input = page.getByLabel("New value for Qty, Line 2");
  await input.fill("6");
  await input.press("Enter");
  await expect(page.getByText("Field corrected")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Qty, Line 2: 6.*corrected/ })).toBeVisible();
  await expect(page.getByText("Fields were corrected. Reassess before approving.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeDisabled();

  // The api refuses too, whatever the page shows.
  const id = page.url().split("/").pop()!;
  const detail = await (await page.request.get(`/api/review/invoices/${id}`)).json();
  expect(detail.needs_revalidation).toBe(true);
  const approve = await page.request.post(`/api/review/invoices/${id}/actions/approve`, { data: { version: detail.version } });
  expect(approve.status()).toBe(409);
  expect((await approve.json()).detail).toMatch(/reassess first/);

  await page.getByRole("button", { name: "Reassess" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reassess" }).click();
  await expect(page.getByText(/sent back for validation/)).toBeVisible();
});

test("invoice queue and detail pages have no serious accessibility violations", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // measure colours after, not during, fade-ins
  await login(page);
  await openInvoices(page);
  expect(await seriousViolations(page)).toEqual([]);
  await page.getByRole("row", { name: new RegExp(REF) }).click();
  await expect(page.getByRole("heading", { name: REF })).toBeVisible();
  await page.getByRole("button", { name: /^Unit price, Line 2: 4,08/ }).click();
  expect(await seriousViolations(page)).toEqual([]);
  for (const tab of [/Header/, /Checks/, /Pipeline/]) {
    await page.getByRole("tab", { name: tab }).click();
    expect(await seriousViolations(page)).toEqual([]);
  }
});
