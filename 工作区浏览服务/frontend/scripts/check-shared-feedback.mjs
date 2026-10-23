import assert from 'node:assert/strict';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

async function fitsViewport(surface, context) {
  const box = await surface.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, right: r.right, bottom: r.bottom,
      width: r.width, viewportWidth: innerWidth, viewportHeight: innerHeight,
      clientWidth: el.clientWidth, scrollWidth: el.scrollWidth };
  });
  assert.ok(box.x >= -1 && box.y >= -1 && box.right <= box.viewportWidth + 1
    && box.bottom <= box.viewportHeight + 1 && box.scrollWidth <= box.clientWidth + 1,
  `[弹窗/消息越界] ${context}: ${JSON.stringify(box)}`);
  return box;
}
async function usableClose(surface, close, context) {
  const result = await close.evaluate(el => {
    const r = el.getBoundingClientRect(), range = document.createRange();
    range.selectNodeContents(el);
    const lines = [...range.getClientRects()].filter(rect => rect.width && rect.height);
    const target = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, height: r.height, width: r.width,
      lines: lines.length, reachable: target === el || el.contains(target) };
  });
  const box = await surface.boundingBox();
  assert.ok(result.left >= box.x - 1 && result.right <= box.x + box.width + 1
    && result.top >= box.y - 1 && result.bottom <= box.y + box.height + 1
    && result.width >= 24 && result.height >= 20 && result.lines === 1 && result.reachable,
  `[关闭按钮不可用] ${context}: ${JSON.stringify(result)}`);
}
async function messageFits(page, card, context) {
  const area = page.getByRole('complementary', { name: '消息通知', exact: true });
  await area.waitFor({ state: 'visible' });
  await card.scrollIntoViewIfNeeded();
  await fitsViewport(area, context);
  const box = await fitsViewport(card, context);
  assert.ok(box.width <= 521, `[消息宽度] ${context}`);
  const contentOverflow = await card.locator('.floating-message-content').evaluate(el => el.scrollWidth > el.clientWidth + 1);
  assert.equal(contentOverflow, false, `[消息内容越界] ${context}`);
  await usableClose(card, card.getByRole('button', { name: '关闭通知', exact: true }), context);
  return box;
}
export async function checkSharedFeedback(page, width, selfTest) {
  const fixture = page.getByTestId('feedback');
  const cards = page.locator('.floating-message');
  for (const trigger of ['打开长内容弹窗', '打开长内容紧凑弹窗']) {
    await fixture.getByRole('button', { name: trigger, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const close = dialog.getByRole('button', { name: '关闭', exact: true });
    await dialog.waitFor({ state: 'visible' });
    const box = await fitsViewport(dialog, `${width}px ${trigger}`);
    if (trigger.includes('紧凑')) assert.ok(box.width <= 441);
    await usableClose(dialog, close, `${width}px 长标题`);
    if (selfTest && width === 390 && trigger === '打开长内容弹窗') {
      let injected = await page.addStyleTag({ content: '.dialog-body{overflow-wrap:normal!important}' });
      await assert.rejects(fitsViewport(dialog, '模拟长串不换行'), /越界/);
      await injected.evaluate(el => el.remove());
      injected = await page.addStyleTag({ content: 'dialog .dialog-close{flex:0 1 auto!important;white-space:normal!important}' });
      await assert.rejects(usableClose(dialog, close, '模拟关闭按钮被挤压'), /关闭按钮不可用/);
      await injected.evaluate(el => el.remove());
      await usableClose(dialog, close, '弹窗恢复后');
      const screenshot = join(tmpdir(), `nora-dialog-${process.pid}.png`);
      await page.screenshot({ path: screenshot });
      console.log(`反向验证：弹窗长串越界和关闭按钮被挤压均被拦截。截图：${screenshot}`);
    }
    assert.equal(await dialog.locator('.dialog-body').evaluate(el => el.scrollWidth > el.clientWidth + 1), false, '[弹窗正文越界]');
    await dialog.evaluate(el => { el.scrollTop = el.scrollHeight; });
    await usableClose(dialog, close, `${width}px 正文滚动到底后`);
    await dialog.evaluate(el => { el.scrollTop = 0; });
    await dialog.getByRole('switch', { name: '模拟禁止关闭' }).click();
    assert.ok(await close.isDisabled());
    await page.keyboard.press('Escape');
    await page.mouse.click(1, 1);
    assert.ok(await dialog.isVisible(), '禁止关闭时Esc/遮罩不能关闭');
    await dialog.getByRole('switch', { name: '模拟禁止关闭' }).click();
    await dialog.getByRole('button', { name: '弹窗内错误提示', exact: true }).click();
    const error = cards.filter({ hasText: '长文字检查' });
    await error.waitFor({ state: 'visible' });
    await messageFits(page, error, `${width}px 弹窗内错误`);
    await error.getByRole('button', { name: '关闭通知' }).click();
    assert.equal(await cards.count(), 0);
    assert.ok(await dialog.isVisible(), '关通知不能关弹窗');
    await dialog.getByRole('button', { name: '弹窗内错误提示', exact: true }).click();
    await close.click();
    assert.equal(await dialog.count(), 0);
    await messageFits(page, cards, `${width}px 弹窗关闭后错误仍保留`);
    await cards.getByRole('button', { name: '关闭通知' }).click();
    await fixture.getByRole('button', { name: trigger, exact: true }).click();
    await page.keyboard.press('Escape');
    assert.equal(await dialog.count(), 0, 'Esc关闭');
    await fixture.getByRole('button', { name: trigger, exact: true }).click();
    await page.mouse.click(1, 1);
    assert.equal(await dialog.count(), 0, '遮罩关闭');
  }
  // Virtual browser time: exact 3s boundary without waiting or testing real operations.
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  await fixture.getByRole('button', { name: '短成功提示', exact: true }).click();
  const short = await messageFits(page, cards, `${width}px 短成功`);
  await page.clock.fastForward(2999);
  assert.equal(await cards.count(), 1, '成功提示不能提前关闭');
  await page.clock.fastForward(1);
  await cards.waitFor({ state: 'hidden' });
  await fixture.getByRole('button', { name: '长成功提示', exact: true }).click();
  const long = await messageFits(page, cards, `${width}px 长成功`);
  assert.ok(long.width > short.width, '消息宽度应随内容变化');
  const infoColor = await cards.evaluate(el => getComputedStyle(el).color);
  await cards.getByRole('button', { name: '关闭通知' }).click();
  assert.equal(await cards.count(), 0, '成功提示可提前手动关闭');
  await fixture.getByRole('button', { name: '长错误提示', exact: true }).click();
  await messageFits(page, cards, `${width}px 长错误`);
  assert.equal(await cards.getAttribute('role'), 'alert');
  assert.notEqual(await cards.evaluate(el => getComputedStyle(el).color), infoColor, '错误提示需有区别样式');
  await page.clock.fastForward(10000);
  assert.equal(await cards.count(), 1, '错误提示不能定时消失');
  if (selfTest && width === 390) {
    let injected = await page.addStyleTag({ content: '.floating-message{min-width:600px!important}' });
    await assert.rejects(messageFits(page, cards, '模拟消息超宽'), /越界|消息宽度/);
    await injected.evaluate(el => el.remove());
    injected = await page.addStyleTag({ content: '.floating-message-close{visibility:hidden!important}' });
    await assert.rejects(usableClose(cards, cards.getByRole('button', { name: '关闭通知', includeHidden: true }), '模拟关闭按钮不可见'), /关闭按钮不可用/);
    await injected.evaluate(el => el.remove());
    await messageFits(page, cards, '消息恢复后');
    const screenshot = join(tmpdir(), `nora-feedback-${process.pid}.png`);
    await page.screenshot({ path: screenshot });
    console.log(`反向验证：消息超宽和关闭按钮不可见均被拦截。截图：${screenshot}`);
  }
  await cards.getByRole('button', { name: '关闭通知' }).click();
  // Multiple long errors remain independently closable even when the stack scrolls.
  for (let i = 0; i < 3; i++) await fixture.getByRole('button', { name: '长错误提示', exact: true }).click();
  assert.equal(await cards.count(), 3);
  for (let remaining = 3; remaining > 0; remaining--) {
    await messageFits(page, cards.last(), `${width}px 消息堆叠`);
    await cards.last().getByRole('button', { name: '关闭通知' }).click();
    assert.equal(await cards.count(), remaining - 1);
  }
  await fixture.getByRole('button', { name: '开始模拟操作' }).click();
  await messageFits(page, cards, `${width}px 持续操作提示`);
  await cards.getByRole('button', { name: '关闭通知' }).click();
  await page.clock.fastForward(5000);
  assert.ok(Number(await fixture.getByTestId('progress').textContent()) > 0, '关提示不能中断操作');
  assert.equal(await cards.count(), 0, '进度更新不能让已关闭提示重新弹出');
  await fixture.getByRole('button', { name: '结束模拟操作' }).click();
  await page.clock.resume();
  const showcase = page.getByTestId('showcase');
  await showcase.getByRole('button', { name: '弹窗与阅读', exact: true }).click();
  await showcase.getByRole('button', { name: '打开长内容弹窗', exact: true }).click();
  const demo = page.getByRole('dialog');
  await fitsViewport(demo, `${width}px 真实展示页长内容弹窗`);
  await usableClose(demo, demo.getByRole('button', { name: '关闭', exact: true }), '展示页关闭');
  await demo.getByRole('button', { name: '关闭', exact: true }).click();
  await showcase.getByRole('button', { name: '消息提示', exact: true }).click();
  await showcase.getByRole('button', { name: '显示长错误提示', exact: true }).click();
  await messageFits(page, cards, `${width}px 真实展示页长错误提示`);
  await cards.getByRole('button', { name: '关闭通知' }).click();
  console.log(`弹窗/消息检查：${width}px长标题正文、普通/紧凑弹窗、关闭/禁用、长短及堆叠消息、3秒成功/持续错误、关闭不取消操作通过。`);
}
