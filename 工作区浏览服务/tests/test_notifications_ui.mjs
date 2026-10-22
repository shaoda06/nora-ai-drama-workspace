// A dedicated fixture imports the real components. No real service or project writes.
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
  server.stdout.on('data', data => {
    output += data;
    const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    if (url) resolve(url);
  });
  server.stderr.on('data', data => { output += data; });
  server.once('error', reject);
  server.once('exit', code => reject(new Error(`Vite exited (${code}): ${output}`)));
});
const out = await mkdtemp(path.join(os.tmpdir(), 'nora-notifications-'));
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    let documentReads = 0;
    await page.route('**/api/**', route => {
      assert.equal(route.request().method(), 'GET');
      documentReads++;
      return route.fulfill({ json: { text: `预览原文第${documentReads}版` } });
    });
    await page.clock.install();
    await page.goto(base + '/tests/notifications.html');
    await page.getByRole('heading', { name: '公共消息组件回归测试' }).waitFor();
    const cards = page.locator('.floating-message');
    const card = text => cards.filter({ hasText: text });
    const click = name => page.getByRole('button', { name, exact: true }).click();
    const count = async number => {
      await page.waitForFunction(number => document.querySelectorAll('.floating-message').length === number, number);
      assert.equal(await cards.count(), number);
    };
    await click('更新文档');
    await card('本文有新版本').waitFor();
    assert.ok(await page.getByRole('heading', { name: '正文第1版' }).isVisible());
    await click('切换页面更新');
    await click('常驻通知');
    await click('普通通知');
    await click('错误通知');
    await count(5);
    assert.equal(await card('本文有新版本').getByRole('button', { name: '关闭通知' }).count(), 0);
    assert.equal(await card('页面已有更新').getByRole('button').count(), 0);
    // Independent close, cleanup and timers must never clear another source.
    await card('音频播放失败').getByRole('button', { name: '关闭通知' }).click();
    await count(4);
    await click('清理常驻通知');
    await count(3);
    await page.clock.runFor(3100);
    await card('普通通知').waitFor({ state: 'detached' });
    await count(2);
    await click('同步失败');
    await card('30秒后重试').waitFor();
    await page.clock.runFor(2000);
    await card('28秒后重试').waitFor();
    await click('同步恢复');
    await count(2);
    await card('本文有新版本').getByRole('button', { name: '读取新版本' }).click();
    await page.getByRole('heading', { name: '正文第2版' }).waitFor();
    await count(1);
    await click('更新文档');
    await card('本文有新版本').waitFor();
    await click('切换文档');
    await count(1);
    // Modal moves the same host above the dialog without restarting notification lifetime.
    await click('普通通知');
    await page.clock.runFor(2000);
    await click('打开预览');
    await page.getByText('预览原文第1版', { exact: true }).waitFor();
    await page.locator('dialog .floating-messages:popover-open').waitFor();
    await page.clock.runFor(1100);
    await card('普通通知').waitFor({ state: 'detached' });
    assert.equal(await card('普通通知').count(), 0);
    await page.evaluate(() => window.dispatchEvent(new Event('fixture-preview-update')));
    await card('项目资料有更新').waitFor();
    await card('项目资料有更新').getByRole('button', { name: '读取新版本' }).click();
    await page.getByText('预览原文第2版', { exact: true }).waitFor();
    assert.equal(documentReads, 2);
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    await page.locator('body > .floating-messages:popover-open').waitFor();
    await count(1);
    await click('常驻通知');
    await click('同步失败');
    await count(3);
    await card('30秒后重试').waitFor();
    // Common frame, no card overlap, no footer/tool overlap, no horizontal overflow.
    const geometry = await page.evaluate(() => {
      const host = document.querySelector('.floating-messages').getBoundingClientRect();
      return {
        host: host.toJSON(),
        footer: document.querySelector('.site-footer').getBoundingClientRect().toJSON(),
        tool: document.querySelector('.back-top').getBoundingClientRect().toJSON(),
        cards: [...document.querySelectorAll('.floating-message')].map(el => ({ ...el.getBoundingClientRect().toJSON(), radius: getComputedStyle(el).borderRadius })),
        scrollWidth: document.documentElement.scrollWidth,
      };
    });
    assert.ok(geometry.host.bottom <= geometry.footer.top - 15);
    assert.ok(geometry.tool.bottom <= geometry.host.top - 11);
    assert.ok(geometry.host.left >= 0 && geometry.host.right <= viewport.width);
    assert.ok(geometry.scrollWidth <= viewport.width);
    geometry.cards.forEach((rect, i) => {
      assert.equal(rect.radius, '8px');
      if (i) assert.ok(rect.top >= geometry.cards[i - 1].bottom + 11);
    });
    await page.screenshot({ path: path.join(out, `${viewport.width}-stack.png`), fullPage: true });
    await click('批量通知');
    await count(18);
    assert.ok(await page.locator('.floating-messages').evaluate(el => el.scrollHeight > el.clientHeight));
    await page.waitForFunction(() => document.querySelector('.back-top').getBoundingClientRect().top >= 0);
    await page.locator('.floating-messages').evaluate(el => { el.scrollTop = el.scrollHeight; });
    await card('多条通知14').getByRole('button', { name: '关闭通知' }).click();
    await count(17);
    assert.deepEqual(errors, []);
    console.log(`${viewport.width}px: independent notifications, timers, countdown, document/preview actions, modal migration, stack geometry and overflow passed`);
    await page.close();
  }
  console.log(`Screenshots: ${out}`);
} finally {
  if (browser) await browser.close();
  server.kill();
}
