import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

async function openWorkspace(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
}

async function register(page: Page, username: string, password: string) {
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Your account is ready");
}

async function signIn(page: Page, username: string, password: string) {
  await page.getByLabel("Email or username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Your collections/ })).toBeVisible();
}

async function createCollection(page: Page, name: string, description = "") {
  await page.getByRole("button", { name: "New collection" }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  if (description) await page.getByLabel("Description").fill(description);
  await page.getByRole("button", { name: "Create collection", exact: true }).click();
}

test("two accounts manage only their own persistent collections", async ({ page }, testInfo) => {
  const suffix = randomUUID().slice(0, 8);
  const first = `reader_${suffix}`;
  const second = `author_${suffix}`;
  const password = `test password ${suffix}`;
  const collection = "Language models";
  const renamed = "Research notes";

  await openWorkspace(page);
  await register(page, first, password);
  await signIn(page, first, password);
  await expect(page.getByText("It starts with a collection.")).toBeVisible();

  await createCollection(page, collection, "Papers to read");
  await expect(page.getByRole("heading", { name: collection, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: collection, exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("workspace.png"), fullPage: true });

  await createCollection(page, collection.toUpperCase());
  await expect(page.getByRole("alert").filter({ hasText: "already exists" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(renamed);
  await page.getByLabel("Description").fill("Findings and notes");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toBeVisible();
  await page.locator(".signout-button").click();

  await register(page, second, password);
  await signIn(page, second, password);
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toHaveCount(0);
  await createCollection(page, renamed);
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toBeVisible();
  await createCollection(page, "Only in the second account");
  await expect(page.getByRole("heading", { name: "Only in the second account" })).toBeVisible();
  await page.locator(".signout-button").click();

  await signIn(page, first, password);
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Only in the second account" })).toHaveCount(0);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toHaveCount(0);
});

test("the account and collections screens fit on a mobile screen", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openWorkspace(page);
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("mobile.png"), fullPage: true });

  const suffix = randomUUID().slice(0, 8);
  const username = `mobile_${suffix}`;
  const password = `test password ${suffix}`;
  await register(page, username, password);
  await signIn(page, username, password);
  await createCollection(page, "Reading list");
  await expect(page.getByRole("heading", { name: "Reading list", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("mobile-workspace.png"), fullPage: true });
});

test("a loading failure is not shown as an empty library and can be retried", async ({ page }) => {
  const suffix = randomUUID().slice(0, 8);
  const username = `retry_${suffix}`;
  const password = `test password ${suffix}`;
  await openWorkspace(page);
  await register(page, username, password);
  await page.route("**/api/v2/collections", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Collections are unavailable right now." }),
  }));
  await signIn(page, username, password);
  await expect(page.getByRole("alert").filter({ hasText: "unavailable" })).toBeVisible();
  await expect(page.getByText("It starts with a collection.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "New collection" })).toBeDisabled();
  await page.unroute("**/api/v2/collections");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("It starts with a collection.")).toBeVisible();
  await expect(page.getByRole("button", { name: "New collection" })).toBeEnabled();
});
