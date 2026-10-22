// Imports the real Result and message host; all read responses belong to this fixture.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '0'], {
  cwd: fileURLToPath(new URL('../frontend', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'],
});
let output = '';
const base = await new Promise((resolve, reject) => {
  server.stdout.on('data', data => { output += data; const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0]; if (url) resolve(url); });
  server.stderr.on('data', data => { output += data; });
  server.once('error', reject);
  server.once('exit', code => reject(new Error(`Vite exited (${code}): ${output}`)));
});
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-read-failure-'));
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport }), errors = [], writes = [], reads = { A: 0, B: 0, Modal: 0 };
    let releaseB, releaseA;
    const holdB = new Promise(resolve => { releaseB = resolve; });
    let holdRetry = false, retrySuccess = false;
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error' && !message.text().includes('503 (Service Unavailable)')) errors.push(message.text()); });
    await page.route('**/api/**', async route => {
      if (route.request().method() !== 'GET') { writes.push(route.request().url()); return route.abort(); }
      const name = new URL(route.request().url()).pathname.split('/').at(-1);
      reads[name]++;
      if (name === 'B') await holdB;
      if (name === 'A' && holdRetry) await new Promise(resolve => { releaseA = resolve; });
      return name === 'A' && retrySuccess
        ? route.fulfill({ json: { text: '读取区A已恢复。' } })
        : route.fulfill({ status: 503, json: { detail: 'read-failure fixture' } });
    });
    await page.goto(base + '/tests/read-failures.html');
    await page.getByRole('heading', { name: '读取失败公共消息回归' }).waitFor();
    const failures = page.locator('.floating-message').filter({ hasText: '资料读取失败，请点击重新读取。' });
    await failures.first().getByRole('button', { name: '重新读取', exact: true }).waitFor();
    assert.equal(await page.locator('main .error, dialog .error').count(), 0, 'no repeated inline error bar');
    assert.equal(await page.locator('main').getByText('资料读取失败，请点击重新读取。', { exact: true }).count(), 0);
    releaseB();
    await failures.nth(1).waitFor();
    assert.deepEqual(reads, { A: 1, B: 1, Modal: 0 });
    assert.equal(await failures.locator('.floating-message-countdown').count(), 0);
    assert.equal(await failures.getByRole('button', { name: '关闭通知', exact: true }).count(), 2);
    await page.getByRole('button', { name: '普通通知', exact: true }).click();
    await page.locator('.floating-message').filter({ hasText: '独立普通通知' }).waitFor({ state: 'detached' });
    assert.equal(await failures.count(), 2, 'retry controls survive ordinary toast expiry');
    holdRetry = true;
    await failures.first().getByRole('button', { name: '重新读取', exact: true }).click();
    await failures.first().getByRole('button', { name: '正在读取…', exact: true }).waitFor();
    assert.equal(await failures.first().getByRole('button', { name: '正在读取…', exact: true }).isEnabled(), false);
    assert.deepEqual(reads, { A: 2, B: 1, Modal: 0 });
    await page.waitForFunction(() => document.querySelectorAll('.floating-message button:disabled').length === 1);
    releaseA();
    await failures.first().getByRole('button', { name: '重新读取', exact: true }).waitFor();
    assert.equal(await failures.count(), 2, 'failed retry updates the existing message');
    holdRetry = false; retrySuccess = true;
    await failures.first().getByRole('button', { name: '重新读取', exact: true }).click();
    await page.getByText('读取区A已恢复。', { exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.floating-message-error').length === 1);
    assert.deepEqual(reads, { A: 3, B: 1, Modal: 0 });
    assert.equal(await page.locator('.floating-message').filter({ hasText: '项目资料有更新' }).count(), 1);
    await page.getByRole('button', { name: '打开失败预览', exact: true }).click();
    await page.locator('dialog .floating-messages:popover-open').waitFor();
    await failures.nth(1).getByRole('button', { name: '重新读取', exact: true }).waitFor();
    assert.equal(await page.getByRole('dialog').locator('.dialog-body .error').count(), 0);
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    await page.locator('body > .floating-messages:popover-open').waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.floating-message-error').length === 1);
    const rect = await failures.first().boundingBox(), footer = await page.locator('.site-footer').boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= viewport.width);
    assert.ok(rect.y + rect.height <= footer.y - 15);
    await page.screenshot({ path: path.join(out, `${viewport.width}-retry-message.png`), fullPage: true });
    await page.getByRole('button', { name: '切换读取区B', exact: true }).click();
    await failures.waitFor({ state: 'detached' });
    assert.equal(await page.locator('.floating-message').count(), 1);
    assert.deepEqual(errors, []); assert.deepEqual(writes, []);
    console.log(`${viewport.width}px: no inline duplicate, persistent retry, disabled pending state, failed/successful retry, source isolation, modal and unmount cleanup passed`);
    await page.close();
  }
  console.log(`Screenshots: ${out}`);
} finally { if (browser) await browser.close(); server.kill(); }
