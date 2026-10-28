// Real production page; temporary APIs and synthetic media only. No real project writes.
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
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-episode-durations-'));
const unexpected = [], writes = [], media = [];
let broken = true;
const doc = { kind: 'document', key: 'fixture.md', name: '示例', version: 'v01', doc: { html: '<p>示例正文</p>' } };
const video = (key, run = 'R001', stage = '一采') => ({ key, run, stage, url: `/fixture/${key}.webm`, candidateNumber: Number(run.slice(1)), approved: false,
  fileRevision: '1', deliveryStatus: '已取回', taskStatus: '成功', checkedAt: '', context: { scriptHtml: '<p>分镜正文</p>', shots: [], prompts: {}, references: { common: [], segment: [] }, issues: [] } });
const entry = (id, duration, run = 'R001', stage = '一采') => ({ id, duration, run, stage, scriptHtml: '<p>计划正文</p>' });
const round = (number, segments) => ({ number, segments, episodeRound: true, created_at: '', script: doc, storyboard: doc, issues: [] });
const episode = name => name === 'EP002' ? { kind: 'group', name, title: '纯计划', script: doc, scenes: ['C001'],
  segments: { C001: [{ id: 'P001', duration: 65.5, videos: [] }] }, productionIssues: [] } : {
  kind: 'group', name, title: '时长示例', script: doc, scenes: ['C001', 'C002', 'C003'], productionIssues: [],
  episodeRounds: [8, 9, 10].map(number => ({ number, scenes: ['C001', 'C002', 'C003'] })),
  sceneRounds: {
    C001: [round(8, [entry('P001', 12)]), round(9, [entry('P001', 12), entry('P002', 13)]), round(10, [entry('P001', 12), entry('P002', 13)])],
    C002: [round(8, [entry('P001', 20, 'R002')]), round(9, [entry('P001', 20), entry('P002', 61)]), round(10, [entry('P001', 20, 'R003', '后处理')])],
    C003: [round(8, [entry('P001', 30)]), round(9, [entry('P001', 75)]), round(10, [entry('P001', 75, 'R003')])],
  },
  segments: {
    C001: [{ id: 'P001', duration: 12, videos: [video('one'), video('unused-candidate', 'R002')] },
      { id: 'P002', duration: 13, videos: [video('two')] }, { id: 'P099', duration: 999, historical: true, videos: [] }],
    C002: [{ id: 'P001', duration: 20, videos: [video('three'), { ...video('primary', 'R003', '后处理'), products: [
      { id: 'process', label: '过程', default: false, key: 'process', url: '/fixture/process.webm', fileRevision: '1' },
      { id: 'final', label: '最终', default: true, key: 'final', url: '/fixture/final.webm', previewUrl: '/fixture/proxy.webm', fileRevision: '1' }] }] },
      { id: 'P002', duration: 61, videos: [] }],
    C003: [{ id: 'P001', duration: 75, videos: [video('broken', 'R003')] }],
  },
};
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)), define: { __APP_VERSION__: JSON.stringify('duration-fixture') }, server: { host: '127.0.0.1', port: 0 },
 plugins: [react(), { name: 'duration-fixture', configureServer(vite) { vite.middlewares.use((req, res, next) => {
  const url = decodeURIComponent(new URL(req.url, 'http://fixture.invalid').pathname);
  if (url.startsWith('/fixture/')) { media.push(url); res.setHeader('Content-Type', 'video/webm'); return res.end(url.endsWith('/broken.webm') && broken ? Buffer.from('invalid video') : sample); }
  if (!url.startsWith('/api/')) return next();
  if (req.method !== 'GET') { writes.push(url); res.writeHead(405); return res.end(); }
  let data;
  if (url === '/api/projects') data = [{ id: '时长示例', name: '时长示例' }];
  else if (url.endsWith('/status')) data = { revision: 1, updating: false, checking: false };
  else if (url.endsWith('/overview')) data = { active: [], warnings: [], directories: [{ name: '00-项目定位', label: '项目定位' }, { name: '09-剧集制作', label: '剧集制作' }] };
  else if (url.endsWith('/sections/00-项目定位')) data = { exists: false, groups: [] };
  else if (url.endsWith('/sections/09-剧集制作')) data = { statistics: { total: 4, completed: 2, notStarted: 0, running: 2 }, children: ['EP001', 'EP002', 'EP003', 'EP004', '片头', '片尾'].map(name => ({ kind: 'group', name, key: name, title: name === 'EP003' ? '很长的题名测试在手机中省略显示不能挤掉时长和制作状态' : '时长示例', titleStatus: '最终定名', statusHtml: '<span class="status-badge status-green">已完成</span>' })) };
  else if (/\/episodes\/(EP00[1-4]|片头|片尾)$/.test(url)) data = episode(url.split('/').at(-1));
  else if (url.includes('/revision-notes/')) data = { rounds: {}, notes: {} };
  else { unexpected.push(url); res.statusCode = 404; data = {}; }
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
 }); } }],
});
await server.listen();
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
 const helpers = await server.ssrLoadModule('/src/components/useEpisodeDurations.ts');
 assert.equal(helpers.formatProductionDuration({ seconds: 59.96, estimated: false }), '1分0秒');
 assert.equal(helpers.formatProductionDuration({ seconds: .3 + .6, estimated: true }), '0.9秒*');
 assert.equal(helpers.formatProductionDuration(null), '时长未记录');
 const planned = helpers.sceneDurationEntries(episode('EP002'), 'C001');
 assert.equal(helpers.formatProductionDuration(helpers.sumProductionDuration(planned, new Map())), '1分5.5秒*');
 for (const width of [1362, 390, 320]) {
  broken = true;
  const context = await browser.newContext({ viewport: { width, height: 916 } });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/project-switch.html#/projects/${encodeURIComponent('时长示例')}`);
  assert.match(await page.title(), /项目切换/);
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP001' }).first().press('Enter');
  const scene = id => page.getByRole('navigation', { name: '本集场次' }).getByRole('button', { name: new RegExp(`^场次 ${id} ·`) });
  const total = page.getByLabel('本集时长', { exact: true });
  const choose = page.getByRole('combobox', { name: '修改轮次', exact: true });
  const chooseRound = async n => { await choose.click(); await page.getByRole('option', { name: new RegExp(`^第${n}轮(?:当前)?$`) }).click(); };
  await page.getByRole('alert').filter({ hasText: '视频时长读取失败' }).waitFor();
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：1分21秒*');
  assert.equal(await scene('C001').textContent(), '场次 C001 · 4秒');
  assert.equal(await scene('C002').textContent(), '场次 C002 · 2秒');
  broken = false;
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：8秒');
  await chooseRound(9);
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：2分22秒*');
  assert.equal(await scene('C002').textContent(), '场次 C002 · 1分3秒*');
  assert.equal(await scene('C003').textContent(), '场次 C003 · 1分15秒*');
  await scene('C002').click();
  assert.equal(await total.textContent(), '本集时长：2分22秒*');
  await chooseRound(8);
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：52秒*');
  assert.equal(await scene('C001').textContent(), '场次 C001 · 2秒');
  await chooseRound(10);
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：8秒');
  await scene('C001').click();
  if (width === 1362) {
    const heading = await page.getByRole('navigation', { name: '当前位置' }).boundingBox();
    const box = await total.boundingBox();
    assert.ok(box.x > heading.x + heading.width / 2, '本集时长在标题行右侧');
  }
  for (const box of await page.getByRole('navigation', { name: '本集场次' }).getByRole('button').evaluateAll(nodes => nodes.map(node => { const b = node.getBoundingClientRect(); return { left: b.left, right: b.right }; }))) {
    assert.ok(box.left >= 0 && box.right <= width + 1, `场次按钮在${width}px内`);
  }
  assert.equal(await page.locator('vite-error-overlay').count(), 0);
  assert.ok(await page.locator('body').evaluate(node => node.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: path.join(screenshots, `${width}.png`), fullPage: false });
  const object = page.getByRole('combobox', { name: '快速选择制作对象', exact: true });
  await object.click(); await page.getByRole('option', { name: /^EP002/ }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="本集时长"]')?.textContent === '本集时长：1分5.5秒*');
  assert.equal(await scene('C001').textContent(), '场次 C001 · 1分5.5秒*');
  await page.getByRole('navigation', { name: '当前位置' }).getByRole('link', { name: '剧集制作' }).click();
  const list = page.getByRole('region', { name: '剧集制作', exact: true });
  const buttons = list.locator('.episode-button');
  await page.waitForFunction(() => document.querySelector('[data-episode="EP001"] .episode-button-duration')?.textContent === '8秒');
  assert.deepEqual(await buttons.locator('.episode-button-duration').allTextContents(), ['8秒', '1分5.5秒*', '8秒', '8秒']);
  const boxes = await buttons.evaluateAll(nodes => nodes.map(node => { const b = node.getBoundingClientRect(); return { x: b.x, y: b.y, right: b.right }; }));
  assert.equal(boxes[0].y === boxes[1].y, width > 700);
  assert.ok(boxes[2].y > boxes[0].y, '列表一行最多两集');
  for (const button of await buttons.all()) {
    const durationBox = await button.locator('.episode-button-duration').boundingBox();
    const statusBox = await button.locator('.status-badge').boundingBox();
    assert.ok(durationBox.x + durationBox.width <= statusBox.x + 1, '时长在制作状态之前');
    assert.ok(await button.evaluate(node => node.scrollWidth <= node.clientWidth + 1));
  }
  assert.ok(boxes.every(box => box.x >= 0 && box.right <= width + 1));
  await page.screenshot({ path: path.join(screenshots, `${width}-list.png`), fullPage: false });
  await buttons.first().click();
  assert.equal(await total.textContent(), '本集时长：8秒', '进入详情沿用相同实际时长');
  for (const shared of ['片头', '片尾']) {
    await object.click(); await page.getByRole('option', { name: new RegExp('^' + shared) }).click();
    await page.waitForFunction(label => document.querySelector('[aria-label="本集时长"]')?.textContent === label + '时长：4秒', shared);
    await scene('C002').click();
    assert.equal(await total.textContent(), shared + '时长：2秒', '切换独立方案只显示该场，不合计为8秒');
    await chooseRound(9);
    await scene('C002').click();
    assert.equal(await total.textContent(), shared + '时长：1分3秒*', '历史轮次及计划时长标记仍随选中场次');
    await chooseRound(10);
    await scene('C001').click();
    assert.equal(await total.textContent(), shared + '时长：4秒', '同一方案的多个P段继续累加');
  }
  await object.click(); await page.getByRole('option', { name: /^EP001/ }).click();
  await scene('C002').click();
  assert.equal(await total.textContent(), '本集时长：8秒', '切回正集仍合计全部场次');
  assert.deepEqual(errors, []);
  await context.close();
 }
 assert.deepEqual(writes, []);
 assert.deepEqual(unexpected, []);
 assert.ok(media.includes('/fixture/final.webm'));
 assert.ok(!media.includes('/fixture/process.webm'), '不读取过程产物');
 assert.ok(!media.includes('/fixture/unused-candidate.webm'), '不累加其他候选');
 console.log(JSON.stringify({ passed: true, viewports: [1362,390,320], screenshots }));
} finally { await browser.close(); await server.close(); }
