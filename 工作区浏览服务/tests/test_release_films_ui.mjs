// Real Project, FileTree, Preview and FileActions; all API responses are local fixtures.
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
const rootFile = file('最终 成片 #1.webm');
const longFile = file('中文长名称与LongUnbrokenReference'.repeat(5) + '.webm', '分平台/');
const tree = { kind: 'group', name: '发布成片', key: '98-发布成片', note: '只读浏览，不修改用户文件。', children: [rootFile,
  { kind: 'group', name: '分平台', children: [longFile] }, { kind: 'group', name: '待导出空目录', children: [] }] };
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
      else if (pathname.endsWith('/sections/00-项目定位')) data = { exists: false, groups: [] };
      else if (pathname.endsWith('/sections/98-发布成片')) {
        if (mode === 'error') { response.statusCode = 503; data = { detail: '本地模拟读取失败' }; }
        else data = mode === 'empty' ? { ...tree, children: [] } : tree;
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
    const entry = page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('button', { name: '发布成片', exact: true });
    await entry.click();
    const panel = page.locator('section.panel:not([hidden])');
    await panel.getByRole('button', { name: rootFile.name, exact: true }).waitFor();
    assert.equal(await entry.getAttribute('aria-current'), 'page');
    assert.deepEqual(await panel.locator(':scope > .tree > *').evaluateAll(els => els.map(el => el.tagName)), ['DIV', 'DETAILS', 'DETAILS']);
    await panel.locator('summary').filter({ hasText: '待导出空目录' }).click();
    assert.equal(await panel.locator('details[open]').count(), 1);
    await panel.locator('summary').filter({ hasText: '分平台' }).click();
    await panel.getByRole('button', { name: longFile.name, exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'long user filename must wrap');
    await panel.getByRole('button', { name: rootFile.name, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: rootFile.name, exact: true });
    await dialog.locator('video').waitFor();
    assert.equal(await dialog.locator('video').evaluate(el => el.autoplay), false);
    await dialog.locator('video').evaluate(async el => { el.muted = true; await el.play(); });
    await page.waitForFunction(() => document.querySelector('dialog video').currentTime > 0);
    await dialog.locator('video').evaluate(el => el.pause());
    const downloadEvent = page.waitForEvent('download');
    await dialog.getByRole('link', { name: '下载', exact: true }).click();
    const download = await downloadEvent;
    assert.deepEqual(await readFile(await download.path()), sample);
    assert.equal(download.suggestedFilename(), rootFile.name);
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'detached' });
    await panel.getByRole('searchbox', { name: '搜索目录', exact: true }).fill('LongUnbrokenReference');
    assert.equal(await panel.getByRole('button', { name: rootFile.name, exact: true }).count(), 0);
    await panel.getByRole('searchbox', { name: '搜索目录', exact: true }).fill('');
    await panel.locator('summary').filter({ hasText: '分平台' }).click();
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-release-tree.png`), animations: 'disabled' });
    mode = 'empty'; await page.reload(); await entry.click();
    await panel.getByText('暂无资料。', { exact: true }).waitFor();
    mode = 'error'; await page.reload(); await entry.click();
    const failure = page.locator('.floating-message').filter({ hasText: '资料读取失败' });
    await failure.getByRole('button', { name: '重新读取', exact: true }).waitFor();
    mode = 'files'; await failure.getByRole('button', { name: '重新读取', exact: true }).click();
    await panel.getByRole('button', { name: rootFile.name, exact: true }).waitFor();
    await failure.waitFor({ state: 'detached' });
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []); assert.deepEqual(writes, []); assert.deepEqual(unexpected, []);
    console.log(`${viewport.width}px: independent entry, original tree/empty folders, long filenames, search, video playback/download bytes, empty/error/retry; no writes or unexpected API passed`);
    await context.close();
  }
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); await server.close(); }
