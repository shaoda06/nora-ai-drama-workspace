// Real Project, ReleaseFilms, TabNav and Pagination; all API responses are local fixtures.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-release-films-'));
const sample = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const file = (name, parent = '') => ({ kind: 'video', name, key: `98-发布成片/${parent}${name}`,
  url: '/api/projects/fixture/files/' + encodeURIComponent(`98-发布成片/${parent}${name}`) });
const rootFile = file('第1集.webm');
const longFile = file('第12集-' + '中文长名称与LongUnbrokenReference'.repeat(5) + '.webm', '子目录/');
const episodes = Array.from({ length: 10 }, (_, index) => file(`第${index + 1}集.webm`)).reverse();
const tree = { kind: 'group', name: '发布成片', key: '98-发布成片', note: '只读浏览，不修改用户文件。', children: [rootFile,
  ...episodes.filter(item => item.name !== rootFile.name),
  { kind: 'group', name: '子目录', children: [file('第11集.webm', '子目录/'), longFile] },
  { kind: 'group', name: '待导出空目录', children: [] },
  { kind: 'text', name: '说明.txt', key: '98-发布成片/说明.txt' }] };
let mode = 'files', unexpected = [], writes = [];
// Serve downloads over real local HTTP; browser route interception cannot reliably complete attachments.
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)),
  define: { __APP_VERSION__: JSON.stringify('release-fixture') }, server: { host: '127.0.0.1', port: 0 },
  plugins: [react(), { name: 'read-only-release-fixture', configureServer(vite) {
    vite.middlewares.use((request, response, next) => {
      const url = new URL(request.url, 'http://fixture.invalid'), pathname = decodeURIComponent(url.pathname);
      if (!pathname.startsWith('/api/')) return next();
      if (request.method !== 'GET') { writes.push(request.url); response.writeHead(405); return response.end(); }
      let data;
      if (pathname.includes('/files/')) {
        response.setHeader('Content-Type', 'video/webm');
        if (url.searchParams.has('download')) response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(rootFile.name)}`);
        return response.end(sample);
      }
      if (pathname.endsWith('/status')) data = { revision: 1, updating: false, checking: false };
      else if (pathname.endsWith('/overview')) data = { project: '发布目录示例', active: [], warnings: [], directories: [
        { name: '00-项目定位', label: '项目定位' }, { name: '09-剧集制作', label: '剧集制作' },
        { name: '98-发布成片', label: '发布成片' }, { name: '08-参考视频', label: '参考视频' }] };
      else if (pathname.endsWith('/sections/00-项目定位')) data = { kind: 'group', children: [
        { ...rootFile, statusHtml: '<span class="status-badge status-green">已确认</span>' },
        { kind: 'group', name: '通用目录', children: [longFile] }] };
      else if (pathname.endsWith('/sections/98-发布成片')) {
        if (mode === 'error') { response.statusCode = 503; data = { detail: '本地模拟读取失败' }; }
        else data = { ...tree, children: mode === 'empty' ? [] : mode === 'single' ? [rootFile] : tree.children };
      } else { unexpected.push(pathname); response.statusCode = 404; data = {}; }
      response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(data));
    });
  } }],
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage(), errors = [];
    mode = 'files'; unexpected = []; writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error' && !message.text().includes('503 (Service Unavailable)')) errors.push(message.text()); });
    await page.goto(base + '/tests/release-films.html');
    assert.equal(await page.title(), '发布成片只读浏览检查');
    const generic = page.locator('section.panel:not([hidden])');
    await generic.getByText('已确认', { exact: true }).waitFor();
    await generic.locator('summary').filter({ hasText: '通用目录' }).click();
    await generic.getByText('未知', { exact: true }).waitFor();
    assert.equal(await generic.getByRole('link', { name: '下载', exact: true }).count(), 2, '通用文件树默认状态及操作保持');
    const entry = page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('button', { name: '发布成片', exact: true });
    await entry.click();
    const panel = page.locator('section.panel:not([hidden])');
    const selector = panel.getByRole('navigation', { name: '发布成片选集', exact: true });
    await selector.getByRole('button', { name: '第1集', exact: true }).waitFor();
    assert.equal(await entry.getAttribute('aria-current'), 'page');
    assert.equal(await page.getByRole('navigation', { name: '项目栏目', exact: true }).locator(':scope > button').last().innerText(), '发布成片');
    assert.equal(await panel.getByRole('searchbox').count(), 0);
    assert.equal(await panel.locator(':scope > p.muted').count(), 0, '不显示目录说明');
    assert.equal(await panel.getByRole('link').count(), 0, '列表不再显示查看和下载');
    assert.equal(await panel.locator('.file-actions, .status-badge').count(), 0, '发布成片不显示确认状态');
    assert.equal(await panel.locator('.tree, details').count(), 0, '取消目录列表');
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第1集', '第2集', '第3集', '第4集', '第5集']);
    await panel.getByText('1 / 3 · 共12集', { exact: true }).waitFor();
    assert.equal(await panel.getByRole('button', { name: '上一页', exact: true }).isDisabled(), true);
    const player = panel.locator('video');
    assert.equal(await player.count(), 1);
    assert.equal(await player.evaluate(el => el.autoplay), false);
    await player.evaluate(async el => { el.muted = true; await el.play(); });
    await page.waitForFunction(() => document.querySelector('section.panel:not([hidden]) video').currentTime > 0);
    const previous = await player.elementHandle();
    await selector.getByRole('button', { name: '第3集', exact: true }).click();
    assert.equal(await previous.evaluate(el => el.isConnected), false, '切集卸载原视频');
    assert.equal(await player.getAttribute('aria-label'), '第3集.webm');
    assert.equal(await player.evaluate(el => el.paused), true);
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第6集', '第7集', '第8集', '第9集', '第10集']);
    assert.equal(await player.getAttribute('aria-label'), '第6集.webm');
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.equal(await selector.getByRole('button').count(), 2);
    assert.equal(await player.getAttribute('aria-label'), '第11集.webm', '子目录视频纳入选集');
    assert.equal(await panel.getByRole('button', { name: '下一页', exact: true }).isDisabled(), true);
    await selector.getByRole('button').last().click();
    assert.equal(await player.getAttribute('aria-label'), longFile.name);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '长名称不得越界');
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-long-name.png`), animations: 'disabled' });
    await panel.getByRole('button', { name: '上一页', exact: true }).click();
    assert.equal(await player.getAttribute('aria-label'), '第6集.webm');
    await player.dispatchEvent('error');
    const mediaFailure = page.locator('.floating-message').filter({ hasText: '无法播放' });
    await mediaFailure.getByRole('button', { name: '重新加载视频', exact: true }).click();
    await mediaFailure.waitFor({ state: 'detached' });
    await player.evaluate(async el => { el.muted = true; await el.play(); });
    await page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('button', { name: '项目定位', exact: true }).click();
    assert.equal(await page.locator('.release-films-player').count(), 0, '离开栏目卸载播放器');
    await entry.click();
    assert.equal(await player.getAttribute('aria-label'), '第1集.webm', '重新进入栏目默认第一集');
    assert.equal(await player.evaluate(el => el.paused), true);
    await page.waitForFunction(() => document.querySelector('section.panel:not([hidden]) video')?.videoWidth > 0);
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-release-player.png`), animations: 'disabled' });
    mode = 'single'; await page.reload(); await entry.click();
    await panel.getByText('1 / 1 · 共1集', { exact: true }).waitFor();
    assert.equal(await panel.getByRole('button', { name: '上一页', exact: true }).isDisabled(), true);
    assert.equal(await panel.getByRole('button', { name: '下一页', exact: true }).isDisabled(), true);
    mode = 'empty'; await page.reload(); await entry.click();
    await panel.getByText('暂无发布成片视频。', { exact: true }).waitFor();
    assert.equal(await player.count(), 0);
    await panel.getByText('1 / 1 · 共0集', { exact: true }).waitFor();
    mode = 'error'; await page.reload(); await entry.click();
    const failure = page.locator('.floating-message').filter({ hasText: '资料读取失败' });
    await failure.getByRole('button', { name: '重新读取', exact: true }).waitFor();
    mode = 'files'; await failure.getByRole('button', { name: '重新读取', exact: true }).click();
    await selector.getByRole('button', { name: '第1集', exact: true }).waitFor();
    await failure.waitFor({ state: 'detached' });
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []); assert.deepEqual(writes, []); assert.deepEqual(unexpected, []);
    console.log(`${viewport.width}px: 5-per-page selection, natural numeric order, 12 videos including subdirectories, one inline player, manual playback, switching/unloading, long names, single/empty pagination, media and read retry; no errors/writes passed`);
    await context.close();
  }
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); await server.close(); }
