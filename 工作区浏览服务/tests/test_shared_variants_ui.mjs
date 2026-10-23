// Real shared components; browser-local fixtures prevent project/queue writes.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[2];
assert.ok(base, 'Usage: node tests/test_shared_variants_ui.mjs URL');
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1362, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 918 }, acceptDownloads: true });
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.route('**/api/**', async route => {
      if (['GET', 'HEAD'].includes(route.request().method())) return route.continue();
      writes.push(route.request().url());
      return route.abort();
    });
    await page.goto(base + '/#/history');
    const nav = page.getByRole('navigation', { name: '开发文档', exact: true });
    await nav.getByRole('button', { name: '公共组件', exact: true }).click();
    const cats = page.getByRole('navigation', { name: '组件分类', exact: true });
    await cats.getByRole('button', { name: '弹窗与阅读', exact: true }).click();
    await page.getByRole('button', { name: '打开紧凑弹窗', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '紧凑弹窗示例', exact: true });
    const close = dialog.getByRole('button', { name: '关闭', exact: true });
    const rect = await dialog.boundingBox();
    assert.ok(rect.width <= 440 && rect.x >= 0 && rect.x + rect.width <= width);
    await dialog.getByRole('switch', { name: '模拟提交中' }).click();
    assert.ok(await close.isDisabled());
    await page.keyboard.press('Escape');
    assert.ok(await dialog.isVisible());
    await page.mouse.click(2, 2);
    assert.ok(await dialog.isVisible());
    await dialog.getByRole('switch', { name: '模拟提交中' }).click();
    await page.keyboard.press('Escape');
    assert.equal(await dialog.count(), 0);
    await page.getByRole('button', { name: '打开紧凑弹窗', exact: true }).click();
    await page.mouse.click(2, 2);
    assert.equal(await dialog.count(), 0);
    await cats.getByRole('button', { name: '下拉菜单', exact: true }).click();
    for (const name of ['表单选项示例', '紧凑选项示例', '小号选项示例', '高亮选项示例']) {
      const select = page.getByRole('combobox', { name, exact: true });
      await select.click();
      const list = page.getByRole('listbox', { name, exact: true });
      assert.equal(await list.locator('[aria-selected=true] .tab-select-badge').textContent(), '当前');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
      assert.equal(await select.getAttribute('aria-expanded'), 'false');
    }
    const dimensions = await page.getByRole('combobox', { name: '高亮选项示例', exact: true }).evaluate(el => {
      const style = getComputedStyle(el); return { size: style.fontSize, height: style.height, padding: style.padding };
    });
    assert.deepEqual(dimensions, { size: '13px', height: '36px', padding: '6px 10px' });
    await cats.getByRole('button', { name: '布局与搜索', exact: true }).click();
    assert.ok(await page.getByRole('searchbox', { name: '禁用搜索示例' }).isDisabled());
    await page.getByRole('searchbox', { name: '紧凑搜索示例' }).fill('找不到');
    assert.ok(await page.getByText('没有匹配的示例。').isVisible());
    if (width < 600) assert.equal(await nav.evaluate(el => getComputedStyle(el).display), 'grid');
    await cats.getByRole('button', { name: '文件与正文', exact: true }).click();
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载本地导出示例', exact: true }).click();
    const download = await pending;
    assert.equal(download.suggestedFilename(), 'component-export.md');
    assert.equal(await readFile(await download.path(), 'utf8'), '本地导出示例。\n');
    assert.ok(await page.getByText('本地导出示例：文件已准备，已交给浏览器保存，请查看下载列表。').isVisible());
    const documentSize = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(documentSize.scroll <= documentSize.width);
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ width, dialogCloseGuard: true, selectVariants: true, search: true, localDownload: true, noBusinessWrites: true }));
    await page.close();
  }
} finally { await browser.close(); }
