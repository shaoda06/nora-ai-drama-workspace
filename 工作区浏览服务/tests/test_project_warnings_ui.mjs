import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const [base, project] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_project_warnings_ui.mjs URL PROJECT');
const api = '/api/projects/' + encodeURIComponent(project);
const url = base + '/#/projects/' + encodeURIComponent(project);
const out = path.join(os.tmpdir(), 'nora-project-warnings-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.addInitScript(({ url, project }) => sessionStorage.setItem('nora-auto-refresh-position', JSON.stringify({
      href: url, scrollY: 0, values: { [`project/${project}/section`]: '09-剧集制作', [`project/${project}/episode`]: 'EP002' },
    })), { url, project });
    await page.route('**/api/**', async route => {
      const request = route.request();
      if (request.method() !== 'GET') return route.abort();
      const pathname = new URL(request.url()).pathname;
      const warningRoute = pathname === api + '/overview' || pathname === api + '/sections/' + encodeURIComponent('09-剧集制作') || pathname === api + '/episodes/EP002';
      if (!warningRoute) return route.continue();
      const response = await route.fetch();
      const data = await response.json();
      data.warnings = ['重复提示测试'];
      if (pathname.endsWith('/EP002')) data.warnings.push('本集独有提示测试');
      await route.fulfill({ response, json: data });
    });
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    const summaries = page.locator('summary').filter({ hasText: /^资料提示/ });
    await summaries.filter({ hasText: '资料提示（2）' }).waitFor();
    assert.equal(await summaries.count(), 1);
    await summaries.click();
    assert.equal(await page.getByText('重复提示测试', { exact: true }).count(), 1);
    assert.equal(await page.getByText('本集独有提示测试', { exact: true }).count(), 1);
    assert.ok(await page.getByText('本集独有提示测试', { exact: true }).isVisible());
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    assert.equal(overflow, false);
    await page.screenshot({ path: path.join(out, `warnings-${width}.png`) });
    await page.getByRole('button', { name: '分集大纲', exact: true }).click();
    await summaries.filter({ hasText: '资料提示（1）' }).waitFor();
    assert.equal(await page.getByText('本集独有提示测试', { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    await page.close();
  }
  // Real project read-only verification: no warning and EP002 links to the formal script.
  const outlines = await (await fetch(base + api + '/sections/' + encodeURIComponent('06-分集大纲'))).json();
  assert.ok(!outlines.warnings.some(message => message.includes('EP002大纲入口未识别')));
  assert.equal(outlines.children.find(item => item.name === 'EP002').key, '09-剧集制作/EP002/02-剧集剧本/EP002-本集剧本.md');
  const real = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await real.addInitScript(({ url, project }) => sessionStorage.setItem('nora-auto-refresh-position', JSON.stringify({
    href: url, scrollY: 0, values: { [`project/${project}/section`]: '09-剧集制作', [`project/${project}/episode`]: 'EP002' },
  })), { url, project });
  await real.route('**/api/**', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await real.goto(url, { waitUntil: 'domcontentloaded' });
  await real.getByRole('button', { name: '查看本集剧本', exact: true }).waitFor();
  assert.equal(real.url(), url);
  assert.ok(await real.title());
  assert.equal(await real.getByText('EP002大纲入口未识别，请核对分集索引。', { exact: true }).count(), 0);
  assert.ok(await real.locator('summary').filter({ hasText: /^资料提示/ }).count() <= 1);
  await real.screenshot({ path: path.join(out, 'real-ep002.png') });
  await real.close();
  console.log(JSON.stringify({ ok: true, viewports: [1280, 390], cases: ['single region', 'deduplicate', 'episode-only warning retained', 'leaving episode clears warning', 'no overflow or console errors', 'formal script outline entry'], screenshots: out }));
} finally { await browser.close(); }
