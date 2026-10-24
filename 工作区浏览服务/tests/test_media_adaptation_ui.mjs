import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-media-adaptation-'));
const dimensions = { landscape: [1440, 1080, '4:3'], portrait: [1080, 1440, '3:4'], square: [512, 512, '1:1'], wide: [1920, 1080, '16:9'] };
const svg = name => { const [width, height] = dimensions[name]; return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#e7f1ed"/><text x="20" y="60" font-size="40">${name}</text></svg>`; };
const writes = [], api = [];
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)), plugins: [react(), {
  name: 'media-adaptation-fixture', configureServer(vite) { vite.middlewares.use((request, response, next) => {
    if (!['GET', 'HEAD'].includes(request.method)) { writes.push(request.url); response.writeHead(405); return response.end(); }
    if (request.url.startsWith('/api/')) { api.push(request.url); response.writeHead(404); return response.end(); }
    const url = new URL(request.url, 'http://fixture.invalid');
    if (!url.pathname.startsWith('/fixture/')) return next();
    const name = url.pathname.split('/').pop();
    const body = name === 'readme.txt' ? '只读示例正文' : svg(name.replace('.svg', ''));
    response.setHeader('Content-Type', name.endsWith('.svg') ? 'image/svg+xml' : 'text/plain; charset=utf-8');
    if (url.searchParams.has('download')) response.setHeader('Content-Disposition', `attachment; filename="${name}"`);
    response.end(body);
  }); },
}], server: { host: '127.0.0.1', port: 0 }, define: { __APP_VERSION__: JSON.stringify('media-fixture') } });
await server.listen();
const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage(), errors = [], failedResponses = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(`${m.text()} @${m.location().url}`); });
    page.on('response', response => { if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`); });
    await page.goto(origin + '/tests/media-adaptation.html');
    assert.equal(await page.title(), '公共菜单与图片预览检查');
    await page.getByRole('heading', { name: '公共菜单与图片预览检查' }).waitFor();
    for (const name of ['短菜单', '候选选择', '长内容菜单', '纯图标菜单']) {
      const combo = page.getByRole('combobox', { name, exact: true });
      await combo.click();
      const menu = page.getByRole('listbox', { name, exact: true });
      const triggerBox = await combo.boundingBox(), box = await menu.boundingBox();
      assert.ok(box.width >= Math.min(triggerBox.width, viewport.width - 16) - 1 && box.width <= viewport.width - 16 + 1, '菜单至少按钮宽，仅受屏幕限制');
      if (name === '短菜单') assert.ok(Math.abs(box.width - triggerBox.width) <= 1, '短内容不额外撑宽');
      if (name === '长内容菜单' && viewport.width === 1362) assert.ok(box.width > 340, '长内容没有固定340px上限');
      if (name === '候选选择') {
        assert.ok(box.width > triggerBox.width + 20, '候选文字和标记自然撑宽');
        const labelBox = await menu.getByRole('option').first().locator('span').first().boundingBox();
        const badgeBox = await menu.locator('.tab-select-badge').boundingBox();
        assert.ok(badgeBox.y < labelBox.y + labelBox.height, '当前标记与候选内容同一行');
        await page.screenshot({ path: path.join(screenshots, `${viewport.width}-candidate.png`), animations: 'disabled' });
      }
      assert.ok(box.x >= 8 && box.x + box.width <= viewport.width - 8 + 1);
      assert.ok(await menu.getByRole('option').evaluateAll(items => items.every(el => el.scrollWidth <= el.clientWidth + 1)), '选项不横向溢出');
      await combo.press('Escape');
    }
    const candidate = page.getByRole('combobox', { name: '候选选择', exact: true });
    await candidate.click(); await candidate.press('ArrowDown'); await candidate.press('Enter');
    assert.equal(await page.getByRole('status', { name: '候选值' }).innerText(), 'two');
    await candidate.click(); await page.getByRole('heading', { name: '公共菜单与图片预览检查', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[role=combobox][aria-label="候选选择"]').getAttribute('aria-expanded') === 'false');
    assert.equal(await candidate.getAttribute('aria-expanded'), 'false', '点击外部关闭');
    const cards = page.locator('.asset-media-card');
    for (const [index, [file, [width, height, ratio]]] of Object.entries(dimensions).entries()) {
      const card = cards.nth(index);
      await card.scrollIntoViewIfNeeded();
      await card.locator('.asset-media-field').filter({ hasText: `${width} × ${height}（${ratio}）` }).waitFor();
      await card.getByRole('button').first().click();
      const dialog = page.getByRole('dialog');
      assert.equal(await dialog.getByRole('link').count(), 1);
      const download = dialog.getByRole('link', { name: '下载', exact: true });
      assert.equal(await dialog.getByRole('link', { name: /查看/ }).count(), 0);
      const actionBox = await download.boundingBox(), bodyBox = await dialog.locator('.dialog-body').boundingBox();
      assert.ok(Math.abs(actionBox.x + actionBox.width / 2 - bodyBox.x - bodyBox.width / 2) <= 1, '图片预览下载在整行居中');
      if (index === 0) {
        const event = page.waitForEvent('download'); await download.click(); const saved = await event;
        assert.equal(saved.suggestedFilename(), file + '.svg');
        assert.equal(await readFile(await saved.path(), 'utf8'), svg(file));
        await page.screenshot({ path: path.join(screenshots, `${viewport.width}-image-preview.png`), animations: 'disabled' });
        await dialog.locator('img').dispatchEvent('error');
        const notice = page.locator('.floating-message').filter({ hasText: '图片无法加载，请下载原文件查看。' });
        await notice.waitFor(); await notice.getByRole('button', { name: '关闭通知', exact: true }).click();
      }
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    }
    const defaults = page.getByRole('region', { name: '原文件操作默认行为' });
    assert.equal(await defaults.getByRole('link').count(), 2, '原FileActions默认行为不变');
    for (const name of ['视频预览', '音频预览', '文档预览']) {
      await page.getByRole('button', { name, exact: true }).click();
      const dialog = page.getByRole('dialog');
      assert.equal(await dialog.getByRole('link').count(), 2, '非图片预览仍保留查看与下载');
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    }
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, [], JSON.stringify(failedResponses));
    console.log(`${viewport.width}px: intrinsic menus, candidate badges/keyboard, 4 actual image ratios, centered download/name/bytes/error, non-image actions passed`);
    await context.close();
  }
  assert.deepEqual(writes, []); assert.deepEqual(api, []);
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); await server.close(); }
