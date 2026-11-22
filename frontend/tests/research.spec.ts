import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('compare saved evidence, edit a note, and export Markdown', async ({ page }) => {
  const summaries = ['a', 'b'].map((id) => ({ analysis_id: id, source_id: id, revision_id: `r-${id}`, filename: `${id}.txt`, title: `Study ${id}`, created_at: '2026-01-01' }));
  let comparisonCreated = false;
  let holdSave = false;
  let finishSave: (() => void) | undefined;
  let note: { id: string; title: string; markdown: string; analysis_ids: string[]; comparison_ids: string[]; version: number; updated_at: string } | null = null;
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let body: unknown;
    if (path.endsWith('/auth/me')) body = { id: 'owner' };
    else if (path.endsWith('/collections')) body = ['Research', 'Other'].map((name, index) => ({ id: `collection${index || ''}`, name, description: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }));
    else if (path.endsWith('/sources') || path.endsWith('/conversations')) body = [];
    else if (path.endsWith('/research')) body = { summaries, comparisons: comparisonCreated ? [{ id: 'comparison', created_at: '2026-01-01' }] : [] };
    else if (path.endsWith('/comparisons') && method === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ summary_ids: ['a', 'b'] });
      comparisonCreated = true; body = { id: 'comparison' };
    } else if (path.endsWith('/comparisons/comparison')) body = { id: 'comparison', caution: 'Check dataset, metric, and evaluation conditions.', sources: summaries.map((row) => ({ ...row, available: true, result: { findings: [{ text: `${row.title} reported a result.`, references: [1] }] }, evidence: [{ number: 1, page: 1, text: `${row.title} supporting passage.` }] })) };
    else if (path.endsWith('/notes') && method === 'GET') body = note ? [note] : [];
    else if ((path.endsWith('/notes') && method === 'POST') || (path.endsWith('/notes/note') && method === 'PATCH')) {
      if (holdSave) await new Promise<void>((resolve) => { finishSave = resolve; });
      const payload = route.request().postDataJSON();
      if (method === 'POST') { expect(payload.analysis_ids).toEqual(['a', 'b']); expect(payload.comparison_ids).toEqual(['comparison']); }
      else expect(payload.version).toBe(note!.version);
      note = { ...payload, id: 'note', version: (note?.version ?? 0) + 1, updated_at: '2026-01-01' }; body = note;
    } else if (path.endsWith('/notes/note/export')) {
      await route.fulfill({ headers: { 'content-type': 'text/markdown', 'content-disposition': 'attachment; filename="note.md"' }, body: `# ${note!.title}\n\n${note!.markdown}\n` }); return;
    } else if (path.endsWith('/notes/note') && method === 'DELETE') { note = null; await route.fulfill({ status: 204 }); return; }
    else throw new Error(`Unexpected request ${method} ${path}`);
    await route.fulfill({ status: 200, json: body });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open documents' }).first().click();
  await page.getByRole('button', { name: 'Research comparisons and notes' }).click();
  await page.getByRole('checkbox', { name: /Study a/ }).check();
  await page.getByRole('checkbox', { name: /Study b/ }).check();
  await page.getByRole('button', { name: 'Compare selected summaries' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.getByText('Study a [1] · Page 1', { exact: true }).click();
  await expect(page.getByText('Study a supporting passage.')).toBeVisible();
  await page.getByLabel('Note title').fill('My comparison');
  await page.getByLabel('Note Markdown').fill('My observations.');
  await page.getByRole('button', { name: 'Attach selected summary findings' }).click();
  await page.getByRole('button', { name: 'Attach current comparison' }).click();
  await page.getByRole('button', { name: 'Save note', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Export Markdown' })).toBeVisible();
  await page.getByLabel('Note Markdown').fill('Unsaved draft.');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Open documents' }).last().click();
  await expect(page.getByLabel('Note Markdown')).toHaveValue('Unsaved draft.');
  await expect(page.getByLabel('Saved notes')).toBeDisabled();
  await page.getByRole('button', { name: 'Discard unsaved edits' }).click();
  await expect(page.getByLabel('Note Markdown')).toHaveValue('My observations.');
  await page.getByLabel('Note Markdown').fill('Updated observations.');
  holdSave = true;
  await page.getByRole('button', { name: 'Save note', exact: true }).click();
  await expect(page.getByLabel('Note Markdown')).toBeDisabled();
  await expect(page.getByLabel('Note title')).toBeDisabled();
  await expect.poll(() => Boolean(finishSave)).toBe(true);
  finishSave!();
  await expect(page.getByRole('button', { name: 'Export Markdown' })).toBeEnabled();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export Markdown' }).click();
  const download = await downloaded;
  expect(await readFile((await download.path())!, 'utf8')).toContain('Updated observations.');
  await page.getByRole('button', { name: 'Delete note', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm note deletion' }).click();
  await expect(page.getByLabel('Note title')).toHaveValue('');
});
