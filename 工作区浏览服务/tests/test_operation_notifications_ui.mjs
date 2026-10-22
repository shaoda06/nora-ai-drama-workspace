// Shared operation messages: all writes and errors are browser-local fixtures.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const frontend = fileURLToPath(new URL('../frontend', import.meta.url));
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '0'], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] });
let output = '';
const base = await new Promise((resolve, reject) => {
  server.stdout.on('data', data => {
    output += data;
    const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    if (url) resolve(url);
  });
  server.stderr.on('data', data => { output += data; });
  server.once('error', reject);
  server.once('exit', code => reject(new Error(`Vite exited (${code}): ${output}`)));
});
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-operation-notifications-'));
let browser;
try {
  browser = await chromium.launch({ headless: true });
  for (const width of [1362, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 918 } }), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => {
      if (window.failCopy) throw new Error('模拟复制失败');
    } } }));
    let failDownload = false, releaseDownload, failNode = true, failNotes = true;
    let config = { revision: '1', nodes: [{ url: 'http://127.0.0.1:8188', username: '', password: '', locked: false, has_auth: false }] };
    const notes = { notes: {}, rounds: { '1': { number: 1, text: '原意见', updatedAt: '2026-10-23T00:00:00Z' } } };
    await page.route('**/fixture-download', async route => {
      await new Promise(resolve => { releaseDownload = resolve; });
      return failDownload ? route.fulfill({ status: 503, json: { detail: '模拟下载失败' } })
        : route.fulfill({ headers: { 'Content-Disposition': 'attachment; filename="fixture.txt"' }, body: 'fixture' });
    });
    await page.route('**/api/**', route => {
      const req = route.request(), url = new URL(req.url());
      if (url.pathname.endsWith('/comfy/config/read')) return route.fulfill({ json: config });
      if (url.pathname.endsWith('/comfy/config')) {
        assert.equal(req.method(), 'PUT');
        if (failNode) return route.fulfill({ status: 409, json: { detail: '模拟节点保存冲突' } });
        config = { ...config, revision: '2', nodes: req.postDataJSON().nodes.map(node => ({ ...node, locked: false, has_auth: false })) };
        return route.fulfill({ json: config });
      }
      if (url.pathname.includes('/revision-notes/')) {
        if (req.method() === 'PUT') {
          if (failNotes) return route.fulfill({ status: 409, json: { detail: '模拟意见保存冲突' } });
          for (const round of req.postDataJSON().rounds) notes.rounds[round.number] = { ...round, updatedAt: '2026-10-23T00:01:00Z' };
        }
        return route.fulfill({ json: notes });
      }
      throw new Error(`Unexpected fixture request ${req.method()} ${url.pathname}`);
    });
    await page.clock.install();
    await page.goto(base + '/tests/operation-notifications.html');
    await page.getByRole('heading', { name: '操作消息回归测试' }).waitFor();
    const cards = page.locator('.floating-message'), card = text => cards.filter({ hasText: text });
    const clear = async () => { for (const button of await page.getByRole('button', { name: '关闭通知', exact: true }).all()) await button.click(); };
    const copy = page.getByRole('button', { name: '复制测试正文', exact: true });
    const toolbar = page.locator('.toolbar'), before = await toolbar.boundingBox();
    await copy.click(); await card('已复制').waitFor();
    assert.deepEqual(await toolbar.boundingBox(), before);
    assert.equal(await toolbar.locator('.notice').count(), 0);
    await clear(); await page.evaluate(() => { window.failCopy = true; });
    await copy.click(); await card('模拟复制失败').waitFor();
    assert.equal(await card('模拟复制失败').getAttribute('role'), 'alert');
    await page.clock.runFor(10000);
    assert.ok(await card('模拟复制失败').isVisible());
    assert.equal(await page.getByLabel('手动复制内容').inputValue(), '测试正文');
    await clear(); await page.evaluate(() => { window.failCopy = false; });
    await copy.click(); await clear();
    const download = page.getByRole('button', { name: '下载测试文件', exact: true });
    await download.click(); await card('正在准备文件').waitFor();
    await card('正在准备文件').getByRole('button', { name: '关闭通知' }).click();
    assert.equal(await cards.count(), 0);
    assert.ok(await page.getByRole('button', { name: '正在准备…', exact: true }).isDisabled());
    const saved = page.waitForEvent('download'); releaseDownload(); const downloaded = await saved;
    assert.equal(downloaded.suggestedFilename(), 'fixture.txt');
    assert.equal(await readFile(await downloaded.path(), 'utf8'), 'fixture');
    await card('已交给浏览器保存').waitFor();
    assert.equal(await card('已交给浏览器保存').locator('.floating-message-countdown').innerText(), '3');
    await page.clock.runFor(3100);
    await card('已交给浏览器保存').waitFor({ state: 'detached' });
    assert.equal(await page.locator('.stage-download-message').count(), 0);
    await clear(); failDownload = true;
    await download.click(); await card('正在准备文件').waitFor(); releaseDownload();
    await card('模拟下载失败').waitFor();
    await page.clock.runFor(10000);
    assert.ok(await card('模拟下载失败').isVisible());
    assert.equal(await card('模拟下载失败').locator('.floating-message-countdown').count(), 0);
    await clear();
    await page.getByRole('button', { name: '编辑测试节点', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '测试节点配置', exact: true });
    await dialog.getByLabel('节点1地址', { exact: true }).fill('http://127.0.0.1:8189');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await card('模拟节点保存冲突').waitFor();
    assert.equal(await dialog.locator('.floating-message-error').count(), 1);
    assert.equal(await dialog.locator('.node-editor-error').count(), 0);
    assert.equal(await dialog.getByLabel('节点1地址', { exact: true }).inputValue(), 'http://127.0.0.1:8189');
    await card('模拟节点保存冲突').getByRole('button', { name: '关闭通知' }).click();
    await dialog.getByLabel('节点1地址', { exact: true }).fill('http://127.0.0.1:8190');
    assert.equal(await card('模拟节点保存冲突').count(), 0);
    assert.equal(await dialog.getByLabel('节点1地址', { exact: true }).inputValue(), 'http://127.0.0.1:8190');
    failNode = false; await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await card('已保存').waitFor(); assert.equal(await card('模拟节点保存冲突').count(), 0);
    await clear(); await dialog.getByRole('button', { name: '‹ 返回', exact: true }).click();
    await page.getByRole('button', { name: '导出修改意见', exact: true }).click();
    const exportDialog = page.getByRole('dialog', { name: 'EP001 · C001 导出修改意见', exact: true });
    const note = exportDialog.getByLabel('第1轮 整场总体意见', { exact: true });
    await note.fill('修改后的意见');
    await exportDialog.getByRole('button', { name: '复制', exact: true }).click();
    await card('已复制；有未保存的修改').waitFor(); await clear();
    await exportDialog.getByRole('button', { name: '保存', exact: true }).click();
    await card('模拟意见保存冲突').waitFor(); assert.equal(await note.inputValue(), '修改后的意见');
    failNotes = false; await exportDialog.getByRole('button', { name: '保存', exact: true }).click();
    await card('已保存。').waitFor(); assert.equal(await card('模拟意见保存冲突').count(), 0);
    const box = await card('已保存。').boundingBox(); assert(box.width <= Math.min(520, width - 72));
    await page.screenshot({ path: path.join(out, `${width}-dialog-save.png`) });
    assert.equal(await page.locator('vite-error-overlay').count(), 0); assert.deepEqual(errors, []);
    await page.close();
    console.log(`PASS ${width}px copy/fallback, download progress/success/error, node save retry, notes copy/save retry, dialog portal and stable layout`);
  }
  console.log(`Evidence: ${out}`);
} finally { await browser?.close(); server.kill('SIGTERM'); }
