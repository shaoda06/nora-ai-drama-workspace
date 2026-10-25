import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
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
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-cover-lineage-'));
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  for (const width of [1362, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 918 } }), errors = [], api = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/api/**', route => { api.push(route.request().url()); return route.abort(); });
    await page.route('**/fixtures/**', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#e6efeb"/></svg>' }));
    await page.goto(base + '/tests/cover-sets.html');
    assert.equal(await page.title(), '封面套组测试');
    const tabs = page.getByRole('navigation', { name: '封面平台', exact: true });
    assert.deepEqual(await tabs.getByRole('button').allTextContents(), ['通用', '抖音', '小红书', '快手']);
    for (const [platform, count] of [['通用', 1], ['抖音', 1], ['小红书', 1], ['快手', 3]]) {
      await tabs.getByRole('button', { name: platform, exact: true }).click();
      assert.equal(await tabs.getByRole('button', { name: platform, exact: true }).getAttribute('aria-current'), 'page');
      const cards = page.locator('.asset-media-card').filter({ visible: true });
      assert.equal(await cards.count(), count);
      for (const title of await cards.locator('h3').allTextContents()) assert.match(title, /^(横版|竖版)封面$/);
      await cards.first().getByRole('button', { name: '查看详情', exact: true }).click();
      const dialog = page.getByRole('dialog');
      assert.equal(await dialog.locator('dd .file-action-links').count(), 2);
      assert.equal(await dialog.getByText('工作区交付预设；实际上传未验证', { exact: true }).count(), 1);
      assert.equal(await dialog.evaluate(el => el.scrollWidth > el.clientWidth), false);
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    }
    const first = page.locator('.asset-media-card').filter({ visible: true }).first();
    assert.match(await first.innerText(), /有新候选待确认/);
    assert.match(await first.innerText(), /v02/);
    await first.getByRole('button', { name: '查看详情', exact: true }).click();
    const dialog = page.getByRole('dialog'), detailTabs = dialog.getByRole('navigation', { name: '封面详情', exact: true });
    await detailTabs.getByRole('button', { name: '最新候选', exact: true }).click();
    assert.equal(await dialog.locator('.asset-media-card').count(), 1);
    assert.match(await dialog.locator('.asset-media-card').innerText(), /v03/);
    await detailTabs.getByRole('button', { name: '版本记录（3）', exact: true }).click();
    assert.deepEqual(await dialog.locator('details.cover-version summary strong').allTextContents(), ['视线调整', '配色整合', '初稿']);
    assert.equal(await dialog.locator('.asset-media-card').filter({ visible: true }).count(), 0);
    const adopted = dialog.locator('details.cover-version').nth(1);
    assert.match(await adopted.locator('summary').innerText(), /当前正式/);
    await adopted.locator('summary').click();
    assert.equal(await adopted.locator('.asset-media-card').filter({ visible: true }).count(), 1);
    assert.equal(await adopted.locator('.cover-library-file .file-action-links').count(), 1);
    await page.screenshot({ path: path.join(out, width + '-versions.png') });
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    assert.equal(await page.locator('.asset-media-card').filter({ visible: true }).count(), 3);
    const unassigned = page.locator('details.cover-library-history');
    assert.match(await unassigned.locator('summary').innerText(), /待归类资料（2）/);
    await unassigned.locator('summary').click();
    assert.equal(await unassigned.locator('.asset-media-card').count(), 0);
    assert.equal(await unassigned.getByText('归属未知的旧图.png', { exact: true }).count(), 1);
    await page.goto(base + '/tests/cover-sets.html?only-kuaishou');
    await tabs.waitFor();
    assert.equal(await tabs.getByRole('button', { name: '小红书', exact: true }).getAttribute('aria-current'), 'page');
    await tabs.getByRole('button', { name: '通用', exact: true }).click();
    assert.equal(await page.getByText('通用暂无已登记的封面。', { exact: true }).count(), 1);
    for (const mode of ['pending', 'empty']) {
      await page.goto(base + '/tests/cover-sets.html?' + mode);
      const card = page.locator('.asset-media-card').first();
      assert.match(await card.innerText(), /尚无正式版/);
      if (mode === 'empty') assert.match(await card.innerText(), /尚未生成图片/);
      else assert.match(await card.locator('img').getAttribute('src'), /PENDING-候选-v01/);
      await card.getByRole('button', { name: '查看详情', exact: true }).click();
      const modal = page.getByRole('dialog');
      if (mode === 'pending') assert.equal(await modal.getByRole('navigation', { name: '封面详情' }).getByRole('button', { name: '最新候选' }).getAttribute('aria-current'), 'page');
      await modal.getByRole('button', { name: '当前正式', exact: true }).click();
      assert.equal(await modal.getByText('尚无已采用且达到目标规格的正式版。', { exact: true }).count(), 1);
      assert.equal(await modal.evaluate(el => el.scrollWidth > el.clientWidth), false);
      await modal.getByRole('button', { name: '关闭', exact: true }).click();
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.deepEqual(errors, []); assert.deepEqual(api, []);
    await page.close(); console.log(width + 'px: stable cover cards, formal/latest separation, revision groups, multi-platform and unclassified/empty states passed');
  }
  console.log('Screenshots: ' + out);
} finally { await browser.close(); server.kill(); }
