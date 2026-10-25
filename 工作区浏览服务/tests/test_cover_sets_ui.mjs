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
    const tabs = page.getByRole('navigation', { name: '封面平台', exact: true });
    assert.deepEqual(await tabs.getByRole('button').allTextContents(), ['通用', '抖音', '小红书', '快手']);
    for (const [platform, count, candidateNames] of [['通用', 1, []], ['抖音', 1, ['多平台候选']], ['小红书', 1, ['多平台候选']], ['快手', 3, ['快手候选']]]) {
      await tabs.getByRole('button', { name: platform, exact: true }).click();
      assert.equal(await tabs.getByRole('button', { name: platform, exact: true }).getAttribute('aria-current'), 'page');
      const cards = page.locator('.asset-media-card').filter({ visible: true });
      assert.equal(await cards.count(), count);
      for (const title of await cards.locator('h3').allTextContents()) assert.ok(title.includes(platform), title);
      const first = cards.first();
      const detailButton = first.getByRole('button', { name: '查看详情', exact: true });
      const edges = await detailButton.evaluate(el => ({ button: el.getBoundingClientRect().right, footer: el.parentElement.getBoundingClientRect().right }));
      assert.ok(Math.abs(edges.button - edges.footer) <= 1, width + 'px cover details right aligned');
      await detailButton.click();
      const dialog = page.getByRole('dialog');
      assert.equal(await dialog.locator('dd .file-action-links').count(), 2);
      assert.equal(await dialog.getByText(itemBasis, { exact: true }).count(), 1);
      assert.equal(await dialog.evaluate(el => el.scrollWidth > el.clientWidth), false);
      await page.screenshot({ path: path.join(out, width + '-' + platform + '-detail.png') });
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
      const history = page.locator('details.cover-library-history').filter({ has: page.locator('summary').filter({ hasText: /^候选与历史/ }) });
      assert.equal(await history.locator('summary').innerText(), '候选与历史（' + candidateNames.length + '）');
      await history.locator('summary').click();
      if (candidateNames.length) await history.locator('.asset-media-card h3').first().waitFor();
      assert.deepEqual(await history.locator('.asset-media-card h3').allTextContents(), candidateNames);
      if (candidateNames.length) {
        await history.getByRole('button', { name: '查看详情', exact: true }).click();
        assert.equal(await page.getByRole('dialog').locator('dd .file-action-links').count(), 1);
        await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
      }
    }
    const legacy = page.locator('details').filter({ has: page.locator('summary').getByText('未登记平台的采用封面（1）', { exact: true }) });
    await legacy.locator('summary').click();
    assert.equal(await legacy.getByRole('heading', { name: '历史封面', exact: true }).count(), 1);
    await legacy.getByRole('button', { name: '查看详情', exact: true }).click();
    assert.equal(await page.getByRole('dialog').locator('dd').getByText('未登记', { exact: true }).count(), 2);
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
    const oldCandidates = page.locator('details').filter({ has: page.locator('summary').getByText('未登记平台的候选与历史（1）', { exact: true }) });
    await oldCandidates.locator('summary').click();
    assert.equal(await oldCandidates.getByRole('heading', { name: '旧候选', exact: true }).count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.deepEqual(errors, []); assert.deepEqual(api, []);
    await page.screenshot({ path: path.join(out, width + '-sets.png') });
    await page.goto(base + '/tests/cover-sets.html?only-kuaishou');
    await tabs.waitFor();
    assert.equal(await tabs.getByRole('button', { name: '小红书', exact: true }).getAttribute('aria-current'), 'page');
    // The shared EP002 file supports both platforms; canonical first populated tab is 小红书.
    await tabs.getByRole('button', { name: '通用', exact: true }).click();
    assert.equal(await page.getByText('通用暂无已登记的采用封面。', { exact: true }).count(), 1);
    assert.equal(await page.locator('.asset-media-card').filter({ visible: true }).count(), 0);
    assert.deepEqual(errors, []); assert.deepEqual(api, []);
    await page.close(); console.log(width + 'px: four platform tabs, shared multi-platform covers/candidates, per-platform empty states and legacy entries passed');
  }
  console.log('Screenshots: ' + out);
} finally { await browser.close(); server.kill(); }
