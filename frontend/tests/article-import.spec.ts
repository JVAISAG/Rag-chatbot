import { expect, test } from "@playwright/test";

test("article imports show progress and the original link", async ({ page }) => {
  let requested = false;
  let polls = 0;
  let refreshPolls = 0;
  let refreshing = false;
  let deleted = false;
  let summarized = false;
  await page.route("**/api/v2/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path.endsWith("/auth/me")) body = { id: "account" };
    else if (path.endsWith("/collections")) body = [{ id: "collection", name: "Articles", description: null, created_at: "2026-01-01", updated_at: "2026-01-01" }];
    else if (path.endsWith("/conversations")) body = [];
    else if (path.endsWith("/sources/import-url")) {
      expect(route.request().postDataJSON()).toEqual({ url: "https://example.com/article" });
      requested = true; body = { job_id: "import-job" };
    } else if (path.endsWith("/jobs/import-job")) {
      polls++; body = { status: polls === 1 ? "running" : "completed", source_id: polls === 1 ? null : "source" };
    } else if (path.endsWith("/sources/source/refresh")) { refreshing = true; body = { job_id: "refresh-job" }; }
    else if (path.endsWith('/sources/source/summaries')) {
      if (route.request().method() === 'POST') { summarized = true; body = { id: 'analysis' }; }
      else body = summarized ? [{ id: 'analysis', created_at: '2026-01-01', revision_id: 'revision' }] : [];
    }
    else if (path.endsWith('/analyses/analysis')) body = { id: 'analysis', revision_id: 'revision', status: 'completed', processed: 1, total: 1, stage: 'map', result: { findings: [{ text: 'A cited summary finding.', references: [1] }] }, evidence: [{ number: 1, page: 1, text: 'Summary supporting passage.' }] };
    else if (path.endsWith("/sources/source") && route.request().method() === "DELETE") {
      deleted = true; await route.fulfill({ status: 204 }); return;
    }
    else if (path.endsWith("/sources")) {
      if (refreshing) refreshPolls++;
      body = requested && polls > 1 && !deleted ? [{ id: "source", filename: "example.com.html", job_id: "extract", status: "ready", title: null, authors: null, publication_date: null, active_revision_id: "revision", replacement_status: null, original_url: "https://example.com/article", refresh_status: refreshing ? (refreshPolls === 1 ? "running" : "completed") : null, refresh_outcome: refreshPolls > 1 ? "unchanged" : null }] : [];
    }
    else throw new Error(`Unexpected request: ${path}`);
    await route.fulfill({ status: 200, json: body });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open documents" }).click();
  await page.getByLabel("Import an article URL").fill("https://example.com/article");
  await page.getByRole("button", { name: "Import article" }).click();
  await expect(page.getByText("Importing article…")).toBeVisible();
  await expect(page.getByText("example.com.html — ready")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open original article" })).toHaveAttribute("href", "https://example.com/article");
  await page.getByRole("button", { name: "Refresh article" }).click();
  await expect(page.getByText("Checking the article for updates; the current version remains available.")).toBeVisible();
  await expect(page.getByText("The article has not changed.")).toBeVisible();
  await page.getByLabel('Document to summarize').selectOption('source');
  await page.getByRole('button', { name: 'Summarize document' }).click();
  await expect(page.getByText('A cited summary finding.', { exact: false })).toBeVisible();
  await page.getByText('Evidence [1] · Page 1').click();
  await expect(page.getByText('Summary supporting passage.')).toBeVisible();
  await page.getByLabel("Delete a document from your library").selectOption("source");
  await expect(page.getByText("Its files will be removed", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page.getByRole("link", { name: "Open original article" })).toHaveCount(0);
});
