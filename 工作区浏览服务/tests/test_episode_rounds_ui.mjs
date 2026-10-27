// Real Project/EpisodeProduction/SceneWorkspace; all APIs and media are local fixtures.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const sample = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-episode-rounds-'));
let missing = false;
const unexpected = [], writes = [];
const video = (scene, run) => ({ key: `${scene}-${run}`, run, stage: '一采', url: missing && run === 'R003' ? '' : `/fixture/${scene}-${run}.mp4`, candidateNumber: Number(run.slice(1)), approved: false,
  fileRevision: '', deliveryStatus: '已取回', taskStatus: '成功', checkedAt: '', context: { scriptHtml: `<p>${scene}-${run}</p>`, shots: [], prompts: {}, references: { common: [], segment: [] }, issues: [] } });
const doc = title => ({ kind: 'document', key: title + '.md', name: title, version: 'v01', doc: { title, html: `<p>${title}的正文</p>` } });
const round = (scene, number, run, shared = true) => ({ number, episodeRound: shared, created_at: '2026-10-26T00:00:00+08:00', script: doc('剧本' + number), storyboard: doc(scene + '分镜' + number), issues: [],
  segments: [{ id: 'P001', duration: 2, stage: '一采', run, scriptHtml: `<p>${scene}-${run}分镜</p>` }] });
const episode = name => ({ kind: 'group', name, title: '轮次示例', children: [], materials: [], previousEpisode: null, warnings: [], productionIssues: [], script: doc('当前剧本'), scenes: ['C001', 'C002'],
  episodeRounds: name === 'EP001' ? [{ number: 8, scenes: ['C001', 'C002'] }, { number: 9, scenes: ['C001', 'C002'] }] : [{ number: 1, scenes: ['C001', 'C002'] }],
  sceneRounds: name === 'EP001' ? { C001: [round('C001', 5, 'R001', false), round('C001', 8, 'R002'), round('C001', 9, 'R002')], C002: [round('C002', 7, 'R001', false), round('C002', 8, 'R001'), round('C002', 9, 'R003')] }
    : { C001: [round('C001', 1, 'R001')], C002: [round('C002', 1, 'R001')] },
  segments: { C001: [{ id: 'P001', duration: 2, videos: [video('C001', 'R001'), video('C001', 'R002'), { ...video('C001', 'R002'), key: 'C001-alternate-R002', url: '/fixture/alternate-R002.mp4' }] }], C002: [{ id: 'P001', duration: 2, videos: [video('C002', 'R001'), video('C002', 'R003')] }] } });
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)), define: { __APP_VERSION__: JSON.stringify('round-fixture') }, server: { host: '127.0.0.1', port: 0 },
 plugins: [react(), { name: 'episode-round-fixture', configureServer(vite) { vite.middlewares.use((req, res, next) => {
  const url = decodeURIComponent(new URL(req.url, 'http://fixture.invalid').pathname);
  if (url.startsWith('/fixture/')) { res.setHeader('Content-Type', 'video/webm'); return res.end(sample); }
  if (!url.startsWith('/api/')) return next();
  if (req.method !== 'GET') { writes.push(url); res.writeHead(405); return res.end(); }
  let data;
  if (url === '/api/projects') data = [{ id: '轮次示例', name: '轮次示例' }];
  else if (url.endsWith('/status')) data = { revision: 1, updating: false, checking: false };
  else if (url.endsWith('/overview')) data = { active: [], warnings: [], directories: [{ name: '00-项目定位', label: '项目定位' }, { name: '09-剧集制作', label: '剧集制作' }] };
  else if (url.endsWith('/sections/00-项目定位')) data = { exists: false, groups: [] };
  else if (url.endsWith('/sections/09-剧集制作')) data = { kind: 'group', statistics: { total: 2, completed: 0, notStarted: 0, running: 2 }, children: ['EP001', 'EP002'].map(name => ({ kind: 'group', name, title: '轮次示例', key: name })) };
  else if (/\/episodes\/EP00[12]$/.test(url)) data = episode(url.slice(-5));
  else if (url.includes('/revision-notes/')) data = { rounds: {}, notes: {} };
  else { unexpected.push(url); res.statusCode = 404; data = {}; }
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
 }); } }],
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
try {
 for (const width of [1362, 390, 320]) {
  missing = false;
  const context = await browser.newContext({ viewport: { width, height: 916 } });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(base + '/tests/project-switch.html#/projects/' + encodeURIComponent('轮次示例'));
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP001' }).first().click();
  const choose = page.getByRole('combobox', { name: '修改轮次', exact: true });
  const scene = id => page.getByRole('button', { name: new RegExp('^场次 ' + id + ' ·') });
  const candidate = page.getByRole('combobox', { name: '版本切换', exact: true });
  const chooseRound = async n => { if (await choose.getAttribute('data-value') === String(n)) return; await choose.click(); await page.getByRole('option', { name: new RegExp(`^第${n}轮(?:当前)?$`) }).click(); };
  const waitRun = async run => page.waitForFunction(run => document.querySelector('[aria-label="版本切换"]')?.getAttribute('data-value')?.endsWith(run), run);
  await choose.waitFor(); assert.equal(await choose.getAttribute('data-value'), '9');
  assert.equal(await page.getByRole('combobox', { name: '场次修改轮次', exact: true }).count(), 0);
  await scene('C002').click(); assert.equal(await choose.getAttribute('data-value'), '9'); await waitRun('R003');
  await chooseRound(8); await waitRun('R001');
  await scene('C001').click(); assert.equal(await choose.getAttribute('data-value'), '8'); await waitRun('R002');
  // Explicitly picking an inherited candidate selects its latest containing episode round.
  await candidate.click(); await page.getByRole('option').filter({ hasText: /^候选二/ }).last().click();
  await page.waitForFunction(() => document.querySelector('[aria-label="修改轮次"]')?.getAttribute('data-value') === '9');
  await page.waitForFunction(() => document.querySelector('[aria-label="版本切换"]')?.getAttribute('data-value') === 'C001-alternate-R002');
  assert.match(await page.locator('.segment-video video').getAttribute('src'), /alternate-R002|blob:/, '自动切轮保留同R中实际选中的文件');
  await scene('C002').click(); await waitRun('R003');
  await candidate.click(); await page.getByRole('option').filter({ hasText: /^候选一/ }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="修改轮次"]')?.getAttribute('data-value') === '8');
  await scene('C001').click();
  const continuous = page.getByRole('checkbox', { name: '连续播放', exact: true });
  await continuous.check(); await page.locator('.segment-video video').dispatchEvent('ended');
  await page.locator('[aria-label="场次 C002 内容"]').waitFor(); await waitRun('R001');
  assert.equal(await choose.getAttribute('data-value'), '8');
  assert.equal(await continuous.isChecked(), true);
  await page.waitForFunction(() => { const v = document.querySelector('.segment-video video'); return v?.autoplay && !v.paused; });
  // A manual scene change keeps the armed episode queue but clears the old auto-arrival.
  await page.locator('.segment-video video').evaluate(video => video.pause());
  await scene('C001').click(); await waitRun('R002');
  assert.equal(await continuous.isChecked(), true, '同集手动切场保留连续播放勾选');
  await page.waitForFunction(() => { const v = document.querySelector('.segment-video video'); return v && !v.autoplay && v.paused; });
  await page.screenshot({ path: path.join(screenshots, `${width}-manual-continuous.png`), fullPage: false });
  await scene('C002').click(); await waitRun('R001');
  assert.equal(await continuous.isChecked(), true, '再次切场仍保持勾选与原轮次');
  await continuous.uncheck();
  await scene('C001').click(); await waitRun('R002');
  assert.equal(await continuous.isChecked(), false, '用户关闭后切场不会重新开启');
  await chooseRound(5); await waitRun('R001');
  await scene('C002').click(); await page.waitForFunction(() => document.querySelector('[aria-label="修改轮次"]')?.getAttribute('data-value') === '7');
  await chooseRound(9);
  // Different episodes have independent counters and retain their own selection.
  const object = page.getByRole('combobox', { name: '快速选择制作对象', exact: true });
  await object.click(); await page.getByRole('option', { name: /^EP002/ }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="修改轮次"]')?.getAttribute('data-value') === '1');
  await object.click(); await page.getByRole('option', { name: /^EP001/ }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="修改轮次"]')?.getAttribute('data-value') === '9');
  const roundsBox = await choose.boundingBox(), sceneBox = await scene('C001').boundingBox();
  await page.screenshot({ path: path.join(screenshots, `${width}.png`), fullPage: false });
  assert.ok(roundsBox.y >= sceneBox.y - 1, '轮次沿用场次同行或窄屏换行布局');
  assert.ok(roundsBox.x >= 0 && roundsBox.x + roundsBox.width <= width);
  await page.screenshot({ path: path.join(screenshots, `${width}.png`), fullPage: false });
  missing = true; await page.reload();
  await scene('C001').click(); await chooseRound(9);
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  await page.locator('.segment-video video').dispatchEvent('ended');
  await page.getByText(/C002.*连续播放已停止/).waitFor();
  assert.equal(await choose.getAttribute('data-value'), '9');
  assert.equal(await scene('C001').getAttribute('aria-current'), 'page');
  await scene('C002').click(); await waitRun('R003');
  assert.equal(await page.locator('.segment-video video').count(), 0, '缺片不能顶替旧视频');
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
  await context.close();
  console.log(`PASS ${width}px: 单集共轮、历史候选联动、跨场实际自动播放、手动切场保留勾选并暂停、主动关闭不恢复、旧记录、跨集独立及缺片停止`);
 }
 console.log('截图：'+screenshots);
} finally { await browser.close(); await server.close(); }
