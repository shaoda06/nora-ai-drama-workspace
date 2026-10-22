// Exercise shared file controls without a production service or real project writes.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const frontend = fileURLToPath(new URL('../frontend', import.meta.url));
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '0'], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] });
let output = '';
const base = await new Promise((resolve, reject) => {
  server.stdout.on('data', data => { output += data; const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0]; if (url) resolve(url); });
  server.stderr.on('data', data => { output += data; });
  server.once('error', reject);
  server.once('exit', code => reject(new Error(`Vite exited (${code}): ${output}`)));
});
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-file-actions-'));
// Chromium downloads bypass request interception; serve the response and attachment header.
const files = createServer((request, response) => {
  const url = new URL(request.url, 'http://localhost');
  response.setHeader('Content-Type', url.pathname.endsWith('.png') ? 'image/svg+xml' : 'text/plain; charset=utf-8');
  if (url.searchParams.has('download')) response.setHeader('Content-Disposition', "attachment; filename*=UTF-8''" + url.pathname.split('/').at(-1));
  response.end(url.pathname.endsWith('.png') ? '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"><rect width="4" height="3" fill="#dce4de"/></svg>' : '# 测试资料卡');
});
await new Promise(resolve => files.listen(0, '127.0.0.1', resolve));
const fileBase = 'http://127.0.0.1:' + files.address().port;
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport }), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.route('**/api/**', route => {
      assert.equal(route.request().method(), 'GET');
      return route.fulfill({ json: { html: '<h2>已打开资料卡</h2>', url: '/fixture/人物.md' } });
    });
    await page.goto(base + '/tests/file-actions.html?files=' + encodeURIComponent(fileBase));
    await page.getByRole('heading', { name: '共用文件操作测试', exact: true }).waitFor();
    for (const name of ['人物', '场景', '道具']) {
      const section = page.getByRole('region', { name, exact: true });
      for (const card of await section.locator('.asset-media-card').all()) {
        const actions = card.locator('.file-action-links');
        assert.equal(await actions.count(), 1);
        const view = await actions.getByRole('link', { name: '查看 ↗', exact: true }).getAttribute('href');
        assert.equal(await card.getByRole('img').getAttribute('src'), view + '?v=1');
        const download = new URL(await actions.getByRole('link', { name: '下载', exact: true }).getAttribute('href'));
        assert.equal(download.pathname, new URL(view, base).pathname);
        assert.equal(download.searchParams.get('download'), 'true');
      }
      const file = section.locator('.file-entry-main').filter({ has: page.getByRole('button', { name: name + '-资料卡.md', exact: true }) });
      const url = new URL(await file.getByRole('link', { name: '下载', exact: true }).getAttribute('href'));
      assert.equal(url.searchParams.get('revision'), '7'); assert.equal(url.hash, '');
      const downloaded = page.waitForEvent('download'); await file.getByRole('link', { name: '下载', exact: true }).click();
      assert.equal((await downloaded).suggestedFilename(), name + '.md');
      await file.getByRole('button').click(); const dialog = page.getByRole('dialog');
      await dialog.getByRole('heading', { name: '已打开资料卡', exact: true }).waitFor();
      assert.equal(await dialog.locator('.file-action-links').count(), 1);
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    }
    assert.equal(await page.getByRole('region', { name: '正文', exact: true }).locator('.file-action-links').count(), 1);
    const cover = page.getByRole('region', { name: '封面', exact: true });
    assert.equal(await cover.locator('.asset-media-card .file-action-links').count(), 0);
    await cover.getByRole('button', { name: '查看详情', exact: true }).click();
    const dialog = page.getByRole('dialog'); assert.equal(await dialog.locator('dd .file-action-links').count(), 2);
    assert.equal(await page.evaluate(() => { const d = document.querySelector('dialog'); return d.scrollWidth > d.clientWidth; }), false);
    await page.screenshot({ path: path.join(out, viewport.width + '-cover.png') });
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(out, viewport.width + '-assets.png'), fullPage: true });
    assert.deepEqual(errors, []); await page.close();
    console.log(viewport.width + 'px: three asset types, formal/candidate files, row associations, downloads, document previews and cover details passed');
  }
  console.log('Screenshots: ' + out);
} finally { await browser.close(); server.kill(); files.close(); }
