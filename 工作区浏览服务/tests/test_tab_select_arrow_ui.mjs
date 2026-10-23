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
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-dropdown-arrow-'));
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
    const page = await browser.newPage({ viewport }), errors = [], api = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/api/**', route => { api.push(route.request().url()); return route.abort(); });
    await page.goto(base + '/tests/tab-select-arrow.html');
    await page.getByRole('heading', { name: '分组下拉箭头回归', exact: true }).waitFor();
    const related = page.getByRole('combobox', { name: '相关资料', exact: true });
    const checkArrow = async () => {
      for (const button of await page.getByRole('combobox').all()) {
        assert.equal(await button.locator('svg').count(), 1, 'only one component arrow');
        assert.equal(await button.evaluate(el => getComputedStyle(el).backgroundImage), 'none', 'no legacy background arrow');
      }
    };
    await checkArrow();
    await related.click();
    await page.getByRole('option', { name: '场景资料', exact: true }).click();
    assert.equal(await page.getByRole('status', { name: '当前页面', exact: true }).innerText(), 'scene');
    assert.equal(await related.getAttribute('data-active'), 'true');
    await checkArrow();
    assert.notEqual(await related.evaluate(el => getComputedStyle(el).color), await page.getByRole('combobox', { name: '参考素材', exact: true }).evaluate(el => getComputedStyle(el).color), 'selected highlight remains');
    await related.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Home'); await page.keyboard.press('Enter');
    assert.equal(await page.getByRole('status', { name: '当前页面', exact: true }).innerText(), 'character');
    await checkArrow();
    await related.click(); await page.keyboard.press('Escape');
    assert.equal(await related.getAttribute('aria-expanded'), 'false');
    await page.getByRole('button', { name: '切换禁用', exact: true }).click();
    for (const button of await page.getByRole('combobox').all()) assert.equal(await button.isDisabled(), true);
    await checkArrow();
    await page.getByRole('button', { name: '切换禁用', exact: true }).click();
    await page.getByRole('button', { name: '项目定位', exact: true }).click();
    assert.equal(await related.getAttribute('data-active'), 'false');
    await checkArrow();
    await page.getByRole('button', { name: '下拉菜单', exact: true }).click();
    await page.getByText('按钮只由组件内的SVG显示一个下拉箭头，选中、高亮或禁用时也不叠加背景箭头。', { exact: true }).waitFor();
    await checkArrow();
    await related.click();
    await page.getByRole('listbox', { name: '相关资料', exact: true }).getByRole('option', { name: '场景资料', exact: true }).click();
    await checkArrow();
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.getByRole('navigation', { name: '项目导航示例', exact: true }).screenshot({ path: path.join(screenshots, `${viewport.width}-single-arrow.png`) });
    assert.deepEqual(errors, []); assert.deepEqual(api, []);
    console.log(`${viewport.width}px: one arrow, active/inactive/disabled, mouse/keyboard selection, Esc and no API/errors passed`);
    await page.close();
  }
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); server.kill(); }
