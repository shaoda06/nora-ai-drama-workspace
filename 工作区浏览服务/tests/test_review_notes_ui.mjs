// Opt-in, read-only browser regression against an existing populated project.
// Every note PUT is intercepted in this browser; production notes are never written.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project, episode, segment, candidate, otherCandidate] = process.argv.slice(2);
assert.ok(base && project && episode && segment && candidate && otherCandidate,
  'Usage: node tests/test_review_notes_ui.mjs URL PROJECT EP P CANDIDATE OTHER_CANDIDATE');
const out = process.env.UI_EVIDENCE_DIR || path.join(os.tmpdir(), 'nora-review-notes-ui');
await mkdir(out, { recursive: true });
const projectPath = '/api/projects/' + encodeURIComponent(project);
const statusPath = projectPath + '/status';
const status = await (await fetch(base + statusPath)).json();
assert.equal(status.updating, false);
assert.equal(status.error, null);
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1531, height: 974 } });
  let phase = 'notes', contexts = 0, episodes = 0, puts = 0;
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    if (request.url().includes('/contexts/')) contexts++;
    if (new URL(request.url()).pathname === projectPath + '/episodes/' + episode) episodes++;
  });
  // Prevent background video preparation, decoding or large downloads during UI QA.
  await page.route(/\.mp4(?:\?|$)/, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  await page.route('**/revision-notes/**', async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    puts++;
    await route.fulfill({ json: { ...route.request().postDataJSON(), updatedAt: new Date().toISOString() } });
  });
  await page.route('**/status', route => new URL(route.request().url()).pathname !== statusPath ? route.continue()
    : route.fulfill({ json: { ...status, revision: status.revision + (phase === 'notes' ? 0 : 1), updating: false, checking: false } }));
  await page.route('**/contexts/**', async route => {
    if (phase !== 'notes') await new Promise(resolve => setTimeout(resolve, 2200));
    await route.continue();
  });
  await page.goto(base + '/#/projects/' + encodeURIComponent(project), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: episode }).first().click();
  await page.getByRole('button', { name: new RegExp('^分段 ' + segment + '，') }).first().click();
  await page.getByRole('combobox', { name: '画质选择' }).selectOption('一采');
  await page.getByRole('combobox', { name: '版本切换' }).selectOption({ label: candidate });
  const figures = page.locator('.segment-reference-images figure');
  await figures.first().waitFor();
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  const edit = page.locator('#revision-note-text');
  await edit.waitFor();
  await page.waitForTimeout(1000);
  const before = { contexts, episodes, figures: await figures.count() };
  for (const text of ['隔离测试第一条', '隔离测试第二条']) {
    await edit.fill(text);
    await page.locator('.revision-note-state[data-state="saved"]').waitFor();
    await page.waitForTimeout(5200);
    assert.equal(contexts, before.contexts, 'note save refetched generation context');
    assert.equal(episodes, before.episodes, 'note save refetched entire episode');
    assert.equal(await figures.count(), before.figures);
    assert.equal(await page.locator('.segment-references .placeholder-label').count(), 0);
    assert.equal(await page.getByText('正在同步资料…', { exact: true }).count(), 0);
  }
  await page.locator('.segment-workspace').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'notes-saved.png') });
  phase = 'content';
  await page.waitForRequest(request => request.url().includes('/contexts/'));
  assert.equal(await figures.count(), before.figures, 'same-candidate reference images disappeared during genuine content refresh');
  assert.equal(await page.locator('.segment-references .placeholder-label').count(), 0);
  assert.equal(await edit.inputValue(), '隔离测试第二条');
  await page.screenshot({ path: path.join(out, 'content-refresh-retained.png') });
  await page.waitForTimeout(2800);
  assert.ok(contexts > before.contexts, 'genuine content change did not refetch');
  await page.getByRole('combobox', { name: '版本切换' }).selectOption({ label: otherCandidate });
  await page.locator('.segment-references .placeholder-label').waitFor();
  assert.equal(await figures.count(), 0, 'different candidate inherited previous reference images');
  await figures.first().waitFor();
  assert.deepEqual(errors, []);
  assert.equal(puts, 2);
  const evidence = { url: page.url(), title: await page.title(), viewport: '1531x974',
    browser: 'Browser plugin not available; bundled Playwright with headless Edge',
    before, after: { contexts, episodes }, interceptedPuts: puts, productionNoteWrites: 0, pageErrors: errors,
    checks: ['two note saves keep episode/context and references stable', 'genuine refresh retains same-candidate references', 'candidate switch clears old references'],
    media: 'Video requests replaced by empty responses for UI-only testing; expected media playback errors are not application errors.' };
  await writeFile(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  await browser.close();
}
