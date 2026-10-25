// Real CoverLibrary grouping and detail checks; fixture media only, no project API.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
const itemBasis = '用户指定；未核实为平台官方规格';
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-cover-sets-'));
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  for (const width of [1362, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 918 } }), errors = [], api = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/api/**', route => { api.push(route.request().url()); return route.abort(); });
    await page.route('**/fixtures/cover.svg*', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#e6efeb"/></svg>' }));
    await page.goto(base + '/tests/cover-sets.html');
    assert.equal(await page.title(), '封面套组测试');
    const first = page.getByRole('region', { name: '封面套组：系列通用', exact: true });
    await first.getByRole('heading', { name: '套组：系列通用', exact: true }).waitFor();
    assert.equal(await first.locator('.asset-media-card').count(), 2);
    assert.equal(await first.getByText('适用平台：快手', { exact: true }).count(), 1);
    assert.equal(await page.getByRole('region', { name: '封面套组：EP002', exact: true }).getByText('适用平台：快手、小红书', { exact: true }).count(), 1);
    const legacy = page.getByRole('region', { name: '封面套组：未登记套组', exact: true });
    assert.equal(await legacy.getByText('适用平台：未登记', { exact: true }).count(), 1);
    assert.equal(await page.locator('.asset-media-card .file-action-links').count(), 0);
    for (const region of [first, page.getByRole('region', { name: '封面套组：EP002', exact: true }), legacy]) {
      await region.getByRole('button', { name: '查看详情', exact: true }).first().click();
      const dialog = page.getByRole('dialog');
      assert.equal(await dialog.locator('dd .file-action-links').count(), 2);
      assert.equal(await dialog.getByText(itemBasis, { exact: true }).count(), 1);
      assert.equal(await dialog.evaluate(el => el.scrollWidth > el.clientWidth), false);
      await page.screenshot({ path: path.join(out, width + '-' + (region === first ? 'detail' : region === legacy ? 'legacy' : 'multi') + '.png') });
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.deepEqual(errors, []); assert.deepEqual(api, []);
    await page.screenshot({ path: path.join(out, width + '-sets.png') });
    await page.close(); console.log(width + 'px: grouped pair, multiple platforms, legacy metadata and detail/file actions passed');
  }
  console.log('Screenshots: ' + out);
} finally { await browser.close(); server.kill(); }
