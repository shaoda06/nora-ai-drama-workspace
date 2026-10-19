// Read-only UI regression. Fixture responses and clipboard writes stay in this browser.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_style_languages_ui.mjs URL PROJECT');
const out = process.env.UI_EVIDENCE_DIR || path.join(os.tmpdir(), 'nora-style-languages-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/api/**', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await page.addInitScript(() => {
    document.execCommand = command => {
      if (command !== 'copy') throw new Error('Unexpected command');
      window.__copiedStyle = document.activeElement.value;
      return true;
    };
  });
  const url = base + '/#/projects/' + encodeURIComponent(project);
  async function openPositioning() {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: '项目定位', exact: true }).click();
    await page.getByRole('heading', { name: '视频执行画风短版', exact: true }).waitFor();
  }
  await openPositioning();
  assert.ok((await page.title()).includes('Nora'));
  const cards = page.locator('.style-sample-card');
  assert.equal(await cards.count(), 2);
  for (const card of await cards.all()) {
    assert.equal(await card.locator('img').count(), 1);
    assert.ok((await card.innerText()).includes('样例版本'));
    assert.ok(!/确认依据|执行记录/.test(await card.innerText()));
  }
  const source = await (await page.request.get(base + '/api/projects/' + encodeURIComponent(project) + '/sections/' + encodeURIComponent('00-项目定位'))).json();
  assert.ok(source.bodyHtml.includes('确认依据') && source.bodyHtml.includes('执行记录'), 'source records were removed');

  await page.screenshot({ path: path.join(out, 'first-viewport.png') });
  await cards.last().locator('li').last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'sample-fields-hidden.png') });
  const fullNav = page.getByRole('navigation', { name: '画风正文语言', exact: true });
  const shortNav = page.getByRole('navigation', { name: '视频画风短版语言', exact: true });
  const full = fullNav.locator('xpath=../..');
  const short = shortNav.locator('xpath=../..');
  assert.equal(await fullNav.count(), 1);
  assert.equal(await shortNav.count(), 1);
  const fullZh = await full.locator('pre').innerText();
  const shortZh = await short.locator('pre').innerText();
  assert.ok(shortZh.startsWith('采用轻微卡通化'));
  await shortNav.getByRole('button', { name: '英文', exact: true }).click();
  const shortEn = await short.locator('pre').innerText();
  assert.ok(shortEn.startsWith('Use a lightly stylized'));
  assert.equal(await full.locator('pre').innerText(), fullZh, 'short selection changed full style');
  await short.getByRole('button', { name: '复制', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__copiedStyle), shortEn);
  await fullNav.getByRole('button', { name: '英文', exact: true }).click();
  assert.equal(await short.locator('pre').innerText(), shortEn);
  await shortNav.getByRole('button', { name: '中文', exact: true }).click();
  assert.equal(await short.locator('pre').innerText(), shortZh);
  assert.notEqual(await full.locator('pre').innerText(), fullZh);
  await short.getByRole('button', { name: '复制', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__copiedStyle), shortZh);
  await page.getByRole('heading', { name: '视频执行画风短版', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'desktop-short-style.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await shortNav.getByRole('button', { name: '英文', exact: true }).click();
  await page.getByRole('heading', { name: '视频执行画风短版', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'mobile-short-style.png') });
  const bounds = await short.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 391, 'short block clips mobile viewport');
  await page.setViewportSize({ width: 1280, height: 1000 });
  let fixture = 'single';
  await page.route('**/sections/**', async route => {
    if (!decodeURIComponent(new URL(route.request().url()).pathname).endsWith('/sections/00-项目定位')) return route.continue();
    const response = await route.fetch();
    const data = await response.json();
    data.bodyHtml = fixture === 'single'
      ? '<h3>画风与美术实现正文</h3><h4>中文</h4><pre><code>完整中文</code></pre><h4>英文</h4><pre><code>Full English</code></pre><h3>视频执行画风短版</h3><h4>中文</h4><pre><code>只有中文短版</code></pre><h3>已确认画风样例</h3>'
      : '<h3>画风与美术实现正文</h3><pre><code>旧完整中文</code></pre><h3>画风与美术实现英文适配</h3><pre><code>Legacy English</code></pre><h3>视频执行画风短版</h3><h4>中文</h4><pre><code>短版中文</code></pre><h4>英文</h4><pre><code>Brief English</code></pre><h3>已确认画风样例</h3>';
    await route.fulfill({ response, json: data });
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('pre code').filter({ hasText: /^只有中文短版$/ }).waitFor();
  assert.equal(await shortNav.count(), 0, 'single-language short invents an English tab');
  await fullNav.getByRole('button', { name: '英文', exact: true }).click();
  assert.equal(await full.locator('pre').innerText(), 'Full English');
  fixture = 'legacy';
  await page.reload({ waitUntil: 'domcontentloaded' });
  await fullNav.waitFor();
  await fullNav.getByRole('button', { name: '英文', exact: true }).click();
  assert.equal(await full.locator('pre').innerText(), 'Legacy English');
  await shortNav.getByRole('button', { name: '英文', exact: true }).click();
  assert.equal(await short.locator('pre').innerText(), 'Brief English');
  assert.deepEqual(errors, []);
  const evidence = { url, title: await page.title(), viewports: ['1280x1000', '390x844'],
    browser: 'Browser plugin not available; bundled Playwright with headless Edge',
    checks: ['independent language tabs', 'copy matches selected language', 'mobile bounds', 'single-language fallback', 'legacy full-style compatibility', 'sample metadata hidden only in presentation'],
    consoleErrors: errors, productionWrites: 0, shortCharacters: { chinese: shortZh.length, english: shortEn.length } };
  await writeFile(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
} finally { await browser.close(); }
