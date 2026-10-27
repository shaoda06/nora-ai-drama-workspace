// Read-only browser fixtures: mock episode data and media; never write project files.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const [base = 'http://127.0.0.1:8782', api = base] = process.argv.slice(2);
const project = '我们的AI短剧';
const release = await (await fetch(base + '/release.json')).json();
const prefix = '/api/projects/' + encodeURIComponent(project);
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const media = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-episode-playback-'));
try {
  const page = await browser.newPage({ viewport: { width: 1362, height: 916 } });
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const data = await (await fetch(api + prefix + '/episodes/EP003')).json();
  const video = (scene, id, run, pending = false) => ({ key: `${scene}-${id}-${run}`, stage: '一采', run, url: pending ? '' : `/fixture-${scene}-${id}-${run}.mp4`, approved: false, candidateNumber: Number(run.slice(1)), fileRevision: '', deliveryStatus: pending ? '未取回' : '已取回', taskStatus: pending ? '排队中' : '成功', context: { scriptHtml: '<p>fixture</p>', shots: [], prompts: {}, references: { common: [], segment: [] }, issues: [] } });
  const round = (number, ids, run) => ({ number, issues: [], segments: ids.map(id => ({ id, duration: 1, stage: '一采', run, scriptHtml: '<p>fixture</p>' })), script: null, storyboard: null });
  data.scenes = ['C001', 'C002', 'C003']; data.episodeRounds = []; data.previousEpisode = null; data.productionIssues = []; data.warnings = [];
  data.materials = []; data.directorSheets = {}; data.storyboards = {};
  data.segments = {
    C001: ['P003', 'P001'].map(id => ({ id, duration: 1, videos: [video('C001', id, 'R001')] })),
    C002: [{ id: 'P004', duration: 1, videos: [video('C002', 'P004', 'R001'), video('C002', 'P004', 'R002')] }],
    C003: [{ id: 'P001', duration: 1, videos: [video('C003', 'P001', 'R001')] }],
  };
  data.sceneRounds = { C001: [round(1, ['P003', 'P001'], 'R001')], C002: [round(1, ['P004'], 'R001'), round(2, ['P004'], 'R002')], C003: [round(1, ['P001'], 'R001')] };
  await page.route('**/api/**', async route => {
    assert.equal(route.request().method(), 'GET', 'fixture must never write');
    const url = new URL(route.request().url());
    if (url.pathname === '/api/service') {
      const service = await (await fetch(api + '/api/service')).json();
      return route.fulfill({ json: { ...service, version: release.version } });
    }
    if (url.pathname === prefix + '/episodes/EP003') return route.fulfill({ json: data });
    if (url.pathname.includes('/revision-notes/')) return route.fulfill({ json: { rounds: {}, notes: {} } });
    const response = await route.fetch({ url: api + url.pathname + url.search });
    return route.fulfill({ response });
  });
  await page.route(/fixture-.*\.mp4(?:\?|$)/, route => route.fulfill({ contentType: 'video/webm', body: media }));
  await page.goto(base + '/#/projects/' + encodeURIComponent(project));
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP003' }).first().click();
  const scene = id => page.getByRole('button', { name: new RegExp('^场次 ' + id + '(?: ·|$)') });
  const checked = page.getByRole('checkbox', { name: '连续播放', exact: true });
  const selectedScene = id => scene(id).getAttribute('aria-current');
  const chooseRound = async number => {
    await page.getByRole('combobox', { name: '场次修改轮次', exact: true }).click();
    await page.getByRole('option', { name: new RegExp('^第' + number + '轮：') }).click();
  };
  const end = () => page.locator('.segment-video video').dispatchEvent('ended');
  // Remember a historical round in the following scene, then start at C001.
  await scene('C002').click(); await chooseRound(1); await scene('C001').click();
  await checked.check(); await end();
  await page.locator('[aria-label^="分段 P001，"][aria-pressed="true"]').waitFor();
  await end();
  await page.locator('[aria-label="场次 C002 内容"]').waitFor({ timeout: 5000 });
  assert.equal(await checked.isChecked(), true, 'keep continuous playback across remount');
  await page.waitForFunction(() => { const video = document.querySelector('.segment-video video'); return video?.autoplay && !video.paused && video.currentTime > 0; });
  await page.screenshot({ path: path.join(out, 'cross-scene-playing.png') });
  assert.match(await page.getByRole('combobox', { name: '版本切换', exact: true }).getAttribute('data-value'), /R001$/, 'respect selected historical round');
  await end();
  await page.locator('[aria-label="场次 C003 内容"]').waitFor();
  await end();
  assert.equal(await selectedScene('C003'), 'page', 'last scene must not wrap');
  // Explicitly cancelling must prevent a later ended event from changing scene.
  await scene('C001').click(); await page.getByRole('button', { name: /^分段 P001，/ }).click();
  assert.equal(await checked.isChecked(), false, 'manual scene selection stops continuous playback');
  await checked.check(); await checked.uncheck(); await end();
  assert.equal(await selectedScene('C001'), 'page');
  // Missing next-scene round or video stops at current scene, without older fallback.
  for (const missing of ['video', 'round']) {
    if (missing === 'video') data.segments.C002[0].videos[0] = video('C002', 'P004', 'R001', true);
    else data.sceneRounds.C002 = [];
    await page.reload();
    await scene('C002').click();
    if (missing === 'video') await chooseRound(1);
    await scene('C001').click(); await page.getByRole('button', { name: /^分段 P001，/ }).click();
    await checked.check(); await end();
    assert.equal(await selectedScene('C001'), 'page');
    await page.getByText(/C002.*连续播放已停止/).waitFor();
  }
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(out, 'missing-next-scene.png') });
  console.log('PASS: intra-scene order, cross-scene handoff, selected round, preserved checkbox, episode end, cancel, missing media/round; no page errors. Evidence:', out);
} finally { await browser.close(); }
