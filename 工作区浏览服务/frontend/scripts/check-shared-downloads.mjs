import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

export async function checkSharedDownloads(page, width) {
  await page.mouse.move(0, 0); // Compare normal styles before the explicit hover checks below.
  const fixture = page.getByTestId('downloads');
  const styles = await fixture.locator('.download-control').evaluateAll(elements => elements.slice(0, 4).map(el => {
    const style = getComputedStyle(el);
    return Object.fromEntries(['fontSize', 'fontWeight', 'lineHeight', 'padding', 'borderRadius', 'color', 'backgroundColor', 'borderColor'].map(key => [key, style[key]]));
  }));
  for (const style of styles) assert.deepEqual(style, styles[0], `${width}px / 页面容器不能覆盖下载外观`);
  assert.equal(styles[0].fontSize, '15px');
  const hoverStyles = [];
  for (const control of [fixture.getByRole('button', { name: '下载检查', exact: true }), fixture.locator('.file-action-links .download-control')]) {
    await control.hover();
    hoverStyles.push(await control.evaluate(el => ({ border: getComputedStyle(el).borderColor, background: getComputedStyle(el).backgroundColor })));
  }
  assert.deepEqual(hoverStyles[0], hoverStyles[1], '按钮和原生链接的悬停外观一致');
  await page.mouse.move(0, 0);
  assert.equal(await fixture.getByRole('button', { name: '下载 API 版', exact: true }).isDisabled(), true);
  for (const button of await fixture.locator('.download-control').all()) {
    const bounds = await button.evaluate(el => {
      const r = el.getBoundingClientRect(), p = el.parentElement.getBoundingClientRect();
      return { left: r.left, right: r.right, parentLeft: p.left, parentRight: p.right, overflow: el.scrollWidth > el.clientWidth + 1 };
    });
    assert.ok(bounds.left >= bounds.parentLeft - 1 && bounds.right <= bounds.parentRight + 1 && !bounds.overflow, JSON.stringify(bounds));
  }
  const native = fixture.locator('.file-action-links .download-control');
  const nativeUrl = new URL(await native.getAttribute('href'));
  assert.equal(nativeUrl.searchParams.get('revision'), '7');
  assert.equal(nativeUrl.searchParams.get('download'), 'true');
  assert.equal(nativeUrl.hash, '');
  const nativeSaved = page.waitForEvent('download');
  await native.click();
  const nativeFile = await nativeSaved;
  assert.equal(nativeFile.suggestedFilename(), 'image.svg');
  assert.match(await readFile(await nativeFile.path(), 'utf8'), /<svg/);
  const localSaved = page.waitForEvent('download');
  await fixture.getByRole('button', { name: '下载检查', exact: true }).click();
  const localFile = await localSaved;
  assert.equal(localFile.suggestedFilename(), 'download-local.md');
  assert.equal(await readFile(await localFile.path(), 'utf8'), '本地下载检查');

  let releaseResponse;
  const responseGate = new Promise(resolve => { releaseResponse = resolve; });
  let attempts = 0;
  await page.route('**/component-samples/download-check.txt', async route => {
    attempts++;
    if (attempts === 1) await responseGate;
    await route.fulfill({ status: 200, headers: attempts === 1 ? {} : { 'Content-Disposition': 'attachment; filename="download-pack.txt"' }, body: '打包下载检查' });
  });
  await fixture.getByRole('button', { name: '打包检查', exact: true }).click();
  const busy = fixture.getByRole('button', { name: '正在打包…', exact: true });
  await busy.waitFor();
  assert.equal(await busy.isDisabled(), true);
  assert.equal(await busy.getAttribute('aria-busy'), 'true');
  assert.equal(await busy.locator('.download-control-spinner').count(), 1);
  await page.getByRole('status').filter({ hasText: '模拟资源' }).getByRole('button', { name: '关闭通知' }).click();
  assert.equal(await busy.isDisabled(), true, '关闭提示不取消下载');
  releaseResponse();
  await page.getByRole('alert').filter({ hasText: '下载响应缺少文件名' }).waitFor();
  const retrySaved = page.waitForEvent('download');
  await fixture.getByRole('button', { name: '打包检查', exact: true }).click();
  const retryFile = await retrySaved;
  assert.equal(retryFile.suggestedFilename(), 'download-pack.txt');
  assert.equal(await readFile(await retryFile.path(), 'utf8'), '打包下载检查');
  const closes = page.getByRole('button', { name: '关闭通知', exact: true });
  while (await closes.count()) await closes.first().click();
  await page.unroute('**/component-samples/download-check.txt');
  await fixture.screenshot({ path: join(tmpdir(), `nora-download-${width}.png`) });
  console.log(`下载组件：${width}px统一外观、长文件名、原文件/本地导出/打包保存、禁用、忙碌、错误重试通过。`);
}
