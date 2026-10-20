// Response-only fixtures: never change real project files, tasks, or media.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_missing_video_ui.mjs URL PROJECT');
const out = path.join(os.tmpdir(), 'nora-missing-video-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1355, height: 925 } });
  const errors = [];
  const consoleErrors = [];
  const fixtureMediaErrors = [];
  const writes = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    // Empty fixture MP4/blob responses cannot satisfy Chrome's media range
    // request. Keep this expected media error separate from application errors.
    (message.text().endsWith('net::ERR_REQUEST_RANGE_NOT_SATISFIABLE') ? fixtureMediaErrors : consoleErrors).push(message.text());
  });
  if (process.env.FRONTEND_DIST) await page.route(base + '/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname !== '/' && !pathname.startsWith('/assets/')) return route.fallback();
    const file = path.join(process.env.FRONTEND_DIST, pathname === '/' ? 'index.html' : pathname);
    const contentType = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    return route.fulfill({ contentType, body: await readFile(file) });
  });
  await page.route('**/api/**', route => {
    if (route.request().method() === 'GET') return route.fallback();
    writes.push(route.request().url());
    return route.abort();
  });
  await page.route(/\.mp4(?:\?|$)/, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  const context = { scriptHtml: '<p>本轮分镜</p>', shots: [], prompts: { chinese: '本轮提示词' }, references: { common: [], segment: [] }, issues: [] };
  const video = (id, run, url = '', taskStatus = '', deliveryStatus = '') => ({ key: `EP001-C001-${id}-${run}-一采${url ? '.mp4' : ''}`,
    url, run, stage: '一采', approved: false, candidateNumber: Number(run.slice(1)), fileRevision: url ? 'fixture' : '', taskStatus, deliveryStatus, checkedAt: '', context });
  const segments = [
    { id: 'P001', videos: [video('P001', 'R003', '/fixture-old.mp4', '成功', '已取回'), video('P001', 'R004')] },
    { id: 'P002', videos: [video('P002', 'R001', '', '成功', '已取回，待人工审阅')] },
    { id: 'P003', videos: [video('P003', 'R001', '/fixture-current.mp4', '成功', '已取回')] },
    { id: 'P004', videos: [video('P004', 'R001', '', '排队中', '未取回')] },
  ].map(segment => ({ ...segment, duration: 3, scriptHtml: '本轮分镜' }));
  await page.route('**/episodes/EP001', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.scenes = ['C001']; data.previousEpisode = null; data.productionIssues = []; data.warnings = [];
    data.segments = { C001: segments };
    data.sceneRounds = { C001: [{ number: 1, issues: [], script: null, storyboard: null,
      segments: segments.map(segment => ({ id: segment.id, duration: 3, stage: '一采', run: segment.id === 'P001' ? 'R004' : 'R001', scriptHtml: '本轮分镜' })) }] };
    await route.fulfill({ response, json: data });
  });
  await page.goto(base + '/#/projects/' + encodeURIComponent(project), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP001' }).first().click();
  await page.getByRole('combobox', { name: '场次修改轮次', exact: true }).waitFor();
  const scene = page.locator('.episode-scene-content');
  const select = id => page.getByRole('button', { name: new RegExp('^分段 ' + id + '，') }).first().click();
  await select('P001');
  await page.screenshot({ path: path.join(out, 'not-generated.png') });
  assert.ok((await scene.innerText()).includes('P001的本轮一采 R004尚未生成视频'), 'planned revision mislabeled as lost media');
  assert.ok(!(await scene.innerText()).includes('视频已不可播放'));
  assert.equal(await page.locator('.segment-video video').count(), 0, 'must not fall back to old R003');
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).click();
  assert.equal(await page.getByRole('checkbox', { name: '连续播放', exact: true }).isChecked(), false);
  assert.ok(!(await scene.locator('[role=alert]').allTextContents()).some(text => text.includes('尚未生成')));
  await select('P002');
  assert.ok((await scene.innerText()).includes('P002的本轮一采 R001已有视频不可播放'));
  assert.ok(!(await scene.innerText()).includes('尚未生成'));
  await page.screenshot({ path: path.join(out, 'unavailable.png') });
  await select('P004');
  assert.ok((await scene.innerText()).includes('尚未生成视频（排队中）'));
  assert.ok(!(await scene.innerText()).includes('已有视频不可播放'));
  await select('P003');
  await page.locator('.segment-video video').dispatchEvent('error');
  await page.getByRole('alert').filter({ hasText: '已有视频不可播放，请打开原文件检查。' }).waitFor();
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  await page.locator('.segment-video video').dispatchEvent('ended');
  assert.equal(await page.getByRole('button', { name: /^分段 P003，/ }).first().getAttribute('aria-pressed'), 'true');
  await scene.getByText('P004的本轮一采 R001尚未生成视频（排队中）', { exact: false }).waitFor();
  assert.ok(!(await scene.locator('[role=alert]').allTextContents()).some(text => text.includes('尚未生成')));
  await select('P001');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'mobile-not-generated.png') });
  assert.deepEqual(errors, []);
  assert.deepEqual(consoleErrors, []);
  assert.deepEqual(writes, []);
  assert.ok((await page.title()).includes('Nora'));
  assert.ok(!(await page.locator('body').innerText()).includes('Internal Server Error'));
  console.log(JSON.stringify({ passed: true, checks: ['planned candidate', 'old candidate not substituted', 'queued candidate', 'missing retrieved video', 'player error', 'continuous start and next segment', 'desktop and mobile'], url: page.url(), pageErrors: errors, consoleErrors, fixtureMediaErrors, productionWrites: writes.length, screenshots: out }));
} finally { await browser.close(); }
