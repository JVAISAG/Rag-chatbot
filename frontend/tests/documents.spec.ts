import { expect, test } from "@playwright/test";

test("documents upload as multipart and extracted text is rendered safely", async ({ page }) => {
  const collection = { id: "collection", name: "Reading", description: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
  const source = { id: "source", filename: "paper.txt", job_id: "job", status: "extracted", title: null as string | null, authors: null as string | null, publication_date: null as string | null, tags: [] as string[], reading_status: 'unread' as 'unread' | 'reading' | 'read', active_revision_id: "revision-1", replacement_status: null as string | null };
  const metadataTags = ['ML', 'retrieval', 'W'.repeat(32)];
  const tagDisplay = 'Tags: ' + metadataTags.join(' · ');
  let uploaded = false;
  let attached = false;
  let created = false;
  let asked = false;
  let quoted = false;
  let waitingQuestion = false;
  let releaseQuestion: () => void = () => { throw new Error('No question is waiting'); };
  let waitingMetadata = false;
  let releaseMetadata: () => void = () => { throw new Error('No metadata save is waiting'); };
  const quotedAnswer = 'Quoted evidence (may answer only part of the question):\n\n“Supporting research passage.” [1]';
  let slowRead = false;
  let pendingRead = false;
  let releaseRead: () => void = () => { throw new Error("No read is waiting"); };
  let slowSearch = false;
  let pendingSearch = false;
  let releaseSearch: () => void = () => { throw new Error("No search is waiting"); };
  await page.route("**/api/v2/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path.endsWith("/auth/me")) body = { id: "account" };
    else if (path.endsWith("/conversations")) {
      if (route.request().method() === "POST") { created = true; body = { id: "conversation" }; }
      else body = created ? [{ id: "conversation", created_at: "2026-01-01T00:00:00Z" }] : [];
    }
    else if (path.endsWith("/messages")) {
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      waitingQuestion = true;
      await new Promise<void>((resolve) => { releaseQuestion = resolve; });
      asked = true; body = { id: "turn", job_id: "answer-job" };
    }
    else if (path.endsWith("/conversations/conversation")) body = { id: "conversation", turns: asked ? [{ id: "turn", question: "What is supported?", answer: quoted ? quotedAnswer : "The evidence supports this result [1].", status: quoted ? "quoted_evidence" : "completed", model: "test", timings: { initial_queue_seconds: 1.5, retrieval_and_rewrite_seconds: 2.5, generation_and_repair_seconds: 4.5 }, evidence: [{ number: 1, text: attached ? "Supporting research passage." : "", available: attached, metadata: { source: "paper.txt", page: 1 } }] }] : [] };
    else if (path.endsWith("/collections")) body = [collection];
    else if (path.endsWith("/sources/source/replace")) {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data;");
      source.replacement_status = "processing"; body = { unchanged: false };
    }
    else if (path.endsWith("/sources/source") && route.request().method() === "PATCH") {
      const { expected_revision_id, ...metadata } = route.request().postDataJSON();
      expect(expected_revision_id).toBe(source.active_revision_id);
      expect(metadata.tags).toEqual(metadataTags);
      expect(metadata.reading_status).toBe('read');
      waitingMetadata = true;
      await new Promise<void>((resolve) => { releaseMetadata = resolve; });
      Object.assign(source, metadata); body = source;
    } else if (path.endsWith("/sources/source")) {
      attached = route.request().method() === "POST";
      await route.fulfill({ status: 204 }); return;
    } else if (path.endsWith("/sources/upload")) {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data;");
      uploaded = true; attached = true; body = source;
    } else if (path === "/api/v2/sources") body = uploaded ? [source] : [];
    else if (path.endsWith("/sources")) body = attached ? [source] : [];
    else if (path.endsWith("/search")) {
      if (slowSearch) { pendingSearch = true; await new Promise<void>((resolve) => { releaseSearch = resolve; }); }
      body = [{ id: "hit", text: "A relevant research passage.", score: 1, metadata: { source: "paper.txt", source_id: "source", revision_id: "revision", page: 1 } }];
    }
    else if (path.endsWith("/retry-index")) { source.status = "ready"; body = { job_id: "job" }; }
    else if (path.endsWith("/text")) {
      if (slowRead) { pendingRead = true; await new Promise<void>((resolve) => { releaseRead = resolve; }); }
      body = { pages: [{ page: 1, text: "<script>window.bad = true</script> Research evidence." }] };
    }
    else throw new Error(`Unexpected request: ${path}`);
    await route.fulfill({ status: path.endsWith("/upload") ? 202 : 200, json: body });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open documents" }).click();
  await page.getByLabel("Upload a document").setInputFiles({ name: "paper.txt", mimeType: "text/plain", buffer: Buffer.from("Research evidence.") });
  await expect(page.getByText("paper.txt — Text extracted")).toBeVisible();
  await page.getByRole("button", { name: "Edit details" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Research paper");
  await page.getByLabel("Authors", { exact: true }).fill("A. Author");
  await page.getByLabel("Publication date").fill("2024-02-29");
  await page.getByLabel('Tags', { exact: true }).fill(metadataTags.join(', '));
  await page.getByLabel('Reading progress', { exact: true }).selectOption('read');
  await page.getByRole("button", { name: "Save details" }).click();
  await expect.poll(() => waitingMetadata).toBe(true);
  await expect(page.getByLabel('Title', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Tags', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Reading progress', { exact: true })).toBeDisabled();
  releaseMetadata();
  await expect(page.getByText("Research paper — Text extracted")).toBeVisible();
  await expect(page.getByText("Authors: A. Author")).toBeVisible();
  await expect(page.getByText("Published: 2024-02-29")).toBeVisible();
  await expect(page.getByText(tagDisplay, { exact: true })).toBeVisible();
  await expect(page.getByText('Reading progress: Read', { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Read text" }).click();
  await expect(page.getByText("<script>window.bad = true</script> Research evidence.", { exact: true })).toBeVisible();
  const reader = page.getByRole('region', { name: 'Source reader', exact: true });
  const questions = page.getByRole('region', { name: 'Collection questions', exact: true });
  const readerBox = await reader.boundingBox();
  const questionsBox = await questions.boundingBox();
  expect(readerBox && questionsBox && readerBox.x + readerBox.width <= questionsBox.x).toBeTruthy();
  await page.locator('.reading-workspace').screenshot({ path: 'test-results/reader-desktop.png' });
  expect(await page.evaluate(() => "bad" in window)).toBe(false);
  await page.getByLabel("Search this collection").fill("research");
  await page.getByRole("button", { name: "Search documents" }).click();
  await expect(page.getByText("A relevant research passage.")).toBeVisible();
  source.status = "indexing_failed";
  await page.getByLabel("Upload a document").setInputFiles({ name: "paper.txt", mimeType: "text/plain", buffer: Buffer.from("Research evidence.") });
  await page.getByRole("button", { name: "Retry indexing paper.txt" }).click();
  await expect(page.getByText("Research paper — ready")).toBeVisible();
  await page.getByLabel("Replace Research paper").setInputFiles({ name: "updated.txt", mimeType: "text/plain", buffer: Buffer.from("Updated evidence.") });
  await expect(page.getByText("Replacement is processing; the current document remains available.")).toBeVisible();
  source.active_revision_id = "revision-2"; source.replacement_status = "published"; source.reading_status = 'unread';
  await expect(page.getByText("Replacement is processing; the current document remains available.")).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByText("<script>window.bad = true</script> Research evidence.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("A relevant research passage.")).toHaveCount(0);
  await expect(page.getByText('Reading progress: Unread', { exact: true })).toBeVisible();
  await expect(page.getByText(tagDisplay, { exact: true })).toBeVisible();
  await page.getByLabel("Your question").fill("What is supported?");
  await page.getByRole("button", { name: "Ask documents" }).click();
  await expect.poll(() => waitingQuestion).toBe(true);
  await expect(page.getByLabel('Your question')).toBeDisabled();
  await expect(page.getByLabel('Conversation', { exact: true })).toBeDisabled();
  releaseQuestion();
  await expect(page.getByText("The evidence supports this result [1].", { exact: true })).toBeVisible();
  await page.getByText('Processing times', { exact: true }).click();
  await expect(page.getByText('Initial queue wait', { exact: true })).toBeVisible();
  await expect(page.getByText('1.5 s', { exact: true })).toBeVisible();
  await expect(page.getByText('Latest generation and evidence checks', { exact: true })).toBeVisible();
  await page.getByText("[1] paper.txt · Page 1", { exact: true }).click();
  await expect(page.getByText("Supporting research passage.")).toBeVisible();
  slowSearch = true;
  await page.getByRole("button", { name: "Search documents" }).click();
  await expect.poll(() => pendingSearch).toBe(true);
  slowRead = true;
  await page.getByRole("button", { name: "Read text" }).click();
  await expect.poll(() => pendingRead).toBe(true);
  await page.getByRole("button", { name: "Remove from collection" }).click();
  await expect(page.getByText("[1] paper.txt · Page 1 · Evidence unavailable", { exact: true })).toBeVisible();
  const completedRead = page.waitForResponse((response) => response.url().endsWith("/sources/source/text"));
  const completedSearch = page.waitForResponse((response) => response.url().endsWith("/collections/collection/search"));
  releaseRead(); releaseSearch();
  await Promise.all([completedRead, completedSearch]);
  await page.waitForTimeout(200);
  await expect(page.getByText("<script>window.bad = true</script> Research evidence.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("A relevant research passage.")).toHaveCount(0);
  await expect(page.getByText("Research paper — ready")).toHaveCount(0);
  await page.getByRole("button", { name: "Add from library" }).click();
  await page.getByLabel("Choose a document").selectOption("source");
  await page.getByRole("button", { name: "Add document", exact: true }).click();
  await expect(page.getByText("Research paper — ready")).toBeVisible();
  await expect(page.getByText("[1] paper.txt · Page 1", { exact: true })).toBeVisible();
  quoted = true;
  await page.reload();
  await page.getByRole("button", { name: "Open documents" }).click();
  await expect(page.getByText(quotedAnswer, { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileReader = await reader.boundingBox();
  const mobileQuestions = await questions.boundingBox();
  expect(mobileReader && mobileQuestions && mobileReader.y + mobileReader.height <= mobileQuestions.y).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.locator('.reading-workspace').screenshot({ path: 'test-results/reader-mobile.png' });
});
