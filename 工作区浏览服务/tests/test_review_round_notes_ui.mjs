// Browser fixtures only: all mutations blocked except in-memory revision-note saves.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project, episode = 'EP002'] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_review_round_notes_ui.mjs URL PROJECT [EP]');
const out = path.join(os.tmpdir(), 'nora-review-round-notes-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1362, height: 918 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const key = note => `${note.roundNumber != null ? `round/${note.roundNumber}/` : ''}${note.segment}/${note.stage}/${note.run}`;
  const old = { roundNumber: 1, segment: 'P002', stage: '一采', run: 'R001', text: '上一轮已确认没有问题', fileRevision: 'fixture', updatedAt: '2026-10-24T10:00:00+08:00' };
  const unknown = { ...old, roundNumber: null, segment: 'P099', text: '轮次不明的历史意见' };
  const saved = { notes: { [key(old)]: old, [key(unknown)]: unknown }, rounds: {} };
  const puts = [];
  await page.route('**/api/**', route => route.request().method() === 'GET' ? route.fallback() : route.abort());
  await page.route(/\.mp4(?:\?|$)/, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  const doc = version => ({ kind: 'document', name: version, key: `fixture/${version}.md`, version, doc: { title: version, html: '<p>模拟轮次资料</p>' } });
  const video = { key: 'fixture-P002-R001', stage: '一采', run: 'R001', url: '/fixture.mp4', fileRevision: 'fixture', candidateNumber: 1, approved: true,
    deliveryStatus: '已取回', taskStatus: '成功', checkedAt: '', context: { scriptHtml: '<p>模拟分镜</p>', shots: [], prompts: {}, references: { common: [], segment: [] }, issues: [] } };
  const segment = { id: 'P002', duration: 3, scriptHtml: '', videos: [video] };
  await page.route(`**/episodes/${episode}`, async route => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ response, json: { ...data, scenes: ['C001'], previousEpisode: null, productionIssues: [], warnings: [], segments: { C001: [segment] },
      sceneRounds: { C001: [1, 2].map(number => ({ number, created_at: `2026-10-24T0${number}:00:00+08:00`, issues: [], script: doc('v' + number), storyboard: doc('v' + number), segments: [{ id: 'P002', duration: 3, stage: '一采', run: 'R001' }] })) } } });
  });
  await page.route('**/revision-notes/**', async route => {
    const request = route.request();
    if (request.method() === 'GET') return route.fulfill({ json: saved });
    assert.equal(request.method(), 'PUT');
    const value = request.postDataJSON();
    puts.push(value);
    if (new URL(request.url()).pathname.endsWith('/export')) {
      for (const note of value.notes) {
        assert.equal(saved.notes[key(note)]?.text ?? '', note.expectedText);
        const { expectedText, ...fields } = note;
        saved.notes[key(note)] = { ...fields, updatedAt: new Date().toISOString() };
      }
      for (const round of value.rounds) saved.rounds[round.number] = { ...round, updatedAt: new Date().toISOString() };
      return route.fulfill({ json: saved });
    }
    assert.ok(value.roundNumber, 'editor must send the selected review round');
    const note = { ...value, updatedAt: new Date().toISOString() };
    saved.notes[key(note)] = note;
    return route.fulfill({ json: note });
  });
  await page.goto(base + '/#/projects/' + encodeURIComponent(project), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: episode }).first().click();
  const choose = page.getByRole('combobox', { name: '场次修改轮次', exact: true });
  await choose.waitFor();
  const chooseRound = async number => { await choose.click(); await page.getByRole('option', { name: new RegExp('^第' + number + '轮：') }).click(); };
  await chooseRound(2);
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  const editor = page.locator('#revision-note-text');
  await editor.waitFor();
  assert.equal(await editor.inputValue(), '', 'inherited video must have an empty new-round editor');
  const openExport = async () => { await page.getByRole('button', { name: '导出修改意见', exact: true }).click(); await page.locator('.revision-export-structured').waitFor(); };
  const closeExport = () => page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  await openExport();
  assert.equal(await page.locator('.revision-export-note').count(), 0, 'old opinions leaked into current round');
  await page.getByRole('button', { name: '全部历史意见', exact: true }).click();
  assert.equal(await page.locator('.revision-export-note').count(), 2);
  assert.ok((await page.locator('.revision-export-structured').innerText()).includes('未标注轮次'));
  await closeExport();
  await editor.fill('本轮对沿用视频的新意见');
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  assert.equal(puts.at(-1).roundNumber, 2);
  await chooseRound(1);
  assert.equal(await editor.inputValue(), old.text);
  await chooseRound(2);
  assert.equal(await editor.inputValue(), '本轮对沿用视频的新意见');
  await openExport();
  assert.equal(await page.locator('.revision-export-note').count(), 1);
  const current = page.locator('.revision-export-note textarea');
  assert.equal(await current.inputValue(), '本轮对沿用视频的新意见');
  await page.getByRole('button', { name: '复制', exact: true }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  assert.ok(copied.includes('第2轮审看意见') && copied.includes('本轮对沿用视频的新意见'));
  assert.ok(!copied.includes(old.text) && !copied.includes(unknown.text));
  await current.fill('本轮导出中修订的意见');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '保存', exact: true }).waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('.revision-export-save button').disabled);
  assert.equal(puts.at(-1).notes[0].roundNumber, 2);
  await page.screenshot({ path: path.join(out, 'current-round.png') });
  await page.getByRole('button', { name: '全部历史意见', exact: true }).click();
  assert.equal(await page.locator('.revision-export-note').count(), 3);
  assert.equal(saved.notes[key(old)].text, old.text);
  assert.equal(saved.notes[key(unknown)].text, unknown.text);
  await page.screenshot({ path: path.join(out, 'all-history.png') });
  await page.getByRole('button', { name: '复制', exact: true }).click();
  const history = await page.evaluate(() => navigator.clipboard.readText());
  assert.ok(history.includes(old.text) && history.includes(unknown.text) && history.includes('本轮导出中修订的意见'));
  await page.setViewportSize({ width: 390, height: 844 });
  const box = await page.getByRole('dialog').boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 391);
  await page.screenshot({ path: path.join(out, 'history-mobile.png') });
  await page.setViewportSize({ width: 1362, height: 918 });
  await closeExport();
  assert.equal(await editor.inputValue(), '本轮导出中修订的意见');
  await page.getByRole('button', { name: '清空', exact: true }).click();
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  await openExport();
  assert.equal(await page.locator('.revision-export-note').count(), 0);
  await closeExport();
  await chooseRound(1);
  assert.equal(await editor.inputValue(), old.text, 'clearing current round modified prior round');
  assert.deepEqual(errors, []);
  assert.equal(await page.title(), 'Nora工作台');
  assert.equal(await page.locator('vite-error-overlay').count(), 0);
  const evidence = { url: page.url(), title: await page.title(), viewport: '1362x918', browser: 'Browser plugin not available; existing Playwright with bundled Chromium',
    checks: ['inherited candidate starts empty', 'editor save includes round', 'switch round restores independent text', 'export only current round', 'history retains prior and unknown rounds', 'export edit preserves round', 'clear current round preserves history'], pageErrors: errors, mockedPuts: puts.length, productionWrites: 0 };
  await writeFile(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
} finally { await browser.close(); }
