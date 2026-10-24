import assert from 'node:assert/strict';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

async function fits(locator, context, scrollable = false) {
  const result = await locator.evaluate((el, scrollable) => {
    const r = el.getBoundingClientRect();
    const buttons = [...el.querySelectorAll('button')].filter(b => b.getClientRects().length);
    return { left: r.left, right: r.right, viewport: innerWidth, width: el.clientWidth, scroll: el.scrollWidth,
      buttons: buttons.map(b => ({ width: b.clientWidth, scroll: b.scrollWidth, height: b.clientHeight, scrollHeight: b.scrollHeight })),
      scrollable };
  }, scrollable);
  assert.ok(result.left >= -1 && result.right <= result.viewport + 1 && (scrollable || result.scroll <= result.width + 1)
    && result.buttons.every(b => b.scroll <= b.width + 1 && b.scrollHeight <= b.height + 1), `[导航边界] ${context}: ${JSON.stringify(result)}`);
}
async function positions(locator) {
  return locator.evaluate(el => [...el.querySelectorAll('button')].filter(b => b.getClientRects().length).map(b => {
    const r = b.getBoundingClientRect(); return { x: r.x, width: r.width, height: r.height };
  }));
}
async function stable(locator, before, context) {
  const after = await positions(locator);
  assert.equal(after.length, before.length);
  after.forEach((r, i) => { for (const key of ['x', 'width', 'height']) assert.ok(Math.abs(r[key] - before[i][key]) <= 1, `[切换晃动] ${context} ${key}: ${before[i][key]} -> ${r[key]}`); });
}
export async function checkSharedNavigation(page, width, selfTest) {
  const fixture = page.getByTestId('navigation');
  for (const id of ['nav-normal', 'nav-group', 'nav-grid', 'nav-scroll', 'underline', 'underline-scroll', 'select-field']) {
    await fixture.getByRole('button', { name: '重置导航', exact: true }).click();
    const host = fixture.getByTestId(id);
    const scrollable = id === 'underline-scroll' || (id === 'nav-scroll' && width <= 600);
    await host.scrollIntoViewIfNeeded();
    await fits(host.locator('nav, [role=combobox]').first(), `${width}/${id}`, scrollable);
    await host.locator('nav').evaluateAll(els => els.forEach(el => { el.scrollLeft = 0; }));
    const before = await positions(host);
    if (id === 'nav-group' || id === 'select-field') {
      const combo = host.getByRole('combobox');
      await combo.click();
      const menu = page.getByRole('listbox', { name: id === 'nav-group' ? '分组长选项' : '长选项下拉', exact: true });
      await fits(menu, `${width}/菜单`);
      const menuBox = await menu.boundingBox();
      assert.ok(menuBox.y >= 0 && menuBox.y + menuBox.height <= 918, '菜单必须处于屏幕内');
      const unavailable = menu.getByRole('option', { name: '不可选择', exact: true });
      assert.equal(await unavailable.isDisabled(), true, '分组/下拉禁用选项必须不可点击');
      // Exercise keyboard skipping as well as pointer selection of a long option.
      await combo.press('ArrowDown');
      const active = await combo.getAttribute('aria-activedescendant');
      assert.equal(await page.locator(`[id="${active}"]`).innerText(), await menu.getByRole('option').last().innerText(), '键盘必须跳过禁用选项');
      await combo.press('Enter');
      assert.equal(await fixture.getByTestId('nav-value').innerText(), 'long');
      await combo.click();
      assert.equal(await menu.getByRole('option', { selected: true }).locator('.tab-select-badge').innerText(), '当前');
      await combo.press('Home'); await combo.press('Enter');
      assert.equal(await fixture.getByTestId('nav-value').innerText(), 'short');
      await combo.click(); await combo.press('End'); await combo.press('ArrowUp'); await combo.press('Enter');
      assert.equal(await fixture.getByTestId('nav-value').innerText(), 'short', '反向跳过禁用');
      await combo.click(); await combo.press('Escape');
      assert.equal(await combo.getAttribute('aria-expanded'), 'false', 'Esc关闭菜单');
      await combo.click(); await menu.getByRole('option').last().click();
      assert.equal(await combo.getAttribute('aria-expanded'), 'false');
      await fits(combo, `${width}/长选项触发器`);
    } else {
      await host.getByRole('button').last().click();
      assert.equal(await fixture.getByTestId('nav-value').innerText(), 'long');
      await fits(host.locator('nav'), `${width}/${id}/选中长文字`, scrollable);
    }
    // Horizontal scroll is intentional in the two scroll variants; normalize it before comparing.
    await host.locator('nav').evaluateAll(els => els.forEach(el => { el.scrollLeft = 0; }));
    await stable(host, before, `${width}/${id}`);
  }
  await fixture.getByRole('button', { name: '切换导航禁用', exact: true }).click();
  for (const button of await fixture.locator('nav > button, [role=combobox]').all()) assert.equal(await button.isDisabled(), true, '整体禁用');
  await fixture.getByRole('button', { name: '切换导航禁用', exact: true }).click();
  for (const name of ['空菜单', '全禁用菜单']) assert.equal(await fixture.getByRole('combobox', { name, exact: true }).isDisabled(), true);
  const pagination = fixture.getByTestId('pagination');
  await fixture.getByRole('button', { name: '首页', exact: true }).click();
  assert.equal(await pagination.getByRole('button', { name: '上一页' }).isDisabled(), true);
  await fixture.getByRole('button', { name: '末页', exact: true }).click();
  assert.equal(await pagination.getByRole('button', { name: '下一页' }).isDisabled(), true);
  await fixture.getByRole('button', { name: '大页码', exact: true }).click();
  await fits(pagination, `${width}/大页码`);
  const largeBefore = await positions(pagination);
  await pagination.getByRole('button', { name: '下一页' }).click();
  await stable(pagination, largeBefore, `${width}/8到9位页码`);
  for (const name of ['单页', '空页']) {
    await fixture.getByRole('button', { name, exact: true }).click();
    assert.equal(await pagination.getByRole('button').count(), 0);
  }
  for (const [id, count] of [['pagination-single', 1], ['pagination-empty', 0]]) {
    const fixed = fixture.getByTestId(id);
    assert.equal(await fixed.getByRole('button').count(), 2, 'alwaysShow单页及空页保留翻页按钮');
    for (const button of await fixed.getByRole('button').all()) assert.equal(await button.isDisabled(), true);
    assert.match(await fixed.innerText(), new RegExp(`共${count}集`), '自定义条目单位');
    await fits(fixed.locator('.pagination'), `${width}/${id}`);
  }
  const filenames = fixture.getByTestId('filename-pagination');
  const compact = filenames.locator('.pagination');
  assert.equal(await compact.locator(':scope > span').count(), 0, '自定义中间内容替代页码和总数');
  assert.equal(await compact.locator('nav > button').count(), 5);
  const layout = await compact.evaluate(el => ({ margin: getComputedStyle(el).marginTop, height: el.getBoundingClientRect().height,
    rows: [...el.querySelectorAll('nav > button')].map(button => button.getBoundingClientRect().top) }));
  assert.equal(layout.margin, '0px');
  assert.ok(layout.height < 65 && layout.rows.every(top => Math.abs(top - layout.rows[0]) < 1), '紧凑文件名保持单行');
  assert.ok(await compact.locator('nav').evaluate(el => el.clientWidth >= 44), '161px窄容器仍保留可点击选集区');
  const boundary = await compact.evaluate(el => ({ left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right, width: el.clientWidth, scroll: el.scrollWidth, viewport: innerWidth }));
  assert.ok(boundary.left >= -1 && boundary.right <= boundary.viewport + 1 && boundary.scroll <= boundary.width + 1, '紧凑分页不越界；文件名内部允许滚动和省略');
  await compact.locator('nav > button').last().click();
  assert.equal(await filenames.getByTestId('filename-value').innerText(), 'long');
  assert.equal(await compact.locator('nav > button').last().getAttribute('title'), await compact.locator('nav > button').last().innerText());
  await fixture.getByRole('button', { name: '第九页', exact: true }).click();
  await fits(pagination, `${width}/分页`);
  const before = await positions(pagination);
  await pagination.getByRole('button', { name: '下一页' }).click();
  assert.equal(await fixture.getByTestId('page-value').innerText(), '10');
  await stable(pagination, before, `${width}/9切10页`);
  await fits(pagination, `${width}/10页`);
  await pagination.getByRole('button', { name: '上一页' }).click();
  assert.equal(await fixture.getByTestId('page-value').innerText(), '9');
  if (selfTest && width === 390) {
    const broken = await page.addStyleTag({ content: '.tabs:not(.tabs-vertical) > button {min-width:700px!important}' });
    await assert.rejects(fits(fixture.getByTestId('nav-normal').locator('nav'), '模拟长选项越界'), /导航边界/);
    await broken.evaluate(el => el.remove());
    const moved = await page.addStyleTag({ content: '.pagination button {transform:translateX(12px)}' });
    await assert.rejects(stable(pagination, before, '模拟分页晃动'), /切换晃动/);
    await moved.evaluate(el => el.remove());
    await stable(pagination, before, '恢复分页');
    console.log('反向验证：导航越界与分页横移均被拦截，恢复后通过。');
  }
  // Isolate fixture containers, not component styles, to cross the actual page scrollbar threshold.
  await fixture.evaluate(el => {
    const siblings = [...el.parentElement.children].filter(child => child !== el);
    const controls = [...el.children].filter(child => !['pagination', 'switch-content'].includes(child.dataset.testid));
    for (const child of [...siblings, ...controls]) { child.dataset.navigationDisplay = child.style.display; child.style.display = 'none'; }
  });
  await page.evaluate(() => scrollTo(0, 0));
  assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1), '短内容应无页面滚动');
  const shortPositions = await positions(pagination);
  await pagination.getByRole('button', { name: '下一页' }).click();
  assert.ok(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight), '长内容应出现页面滚动');
  await stable(pagination, shortPositions, `${width}/页面滚动条出现`);
  await pagination.getByRole('button', { name: '上一页' }).click();
  await stable(pagination, shortPositions, `${width}/页面滚动条消失`);
  await page.evaluate(() => document.querySelectorAll('[data-navigation-display]').forEach(el => {
    el.style.display = el.dataset.navigationDisplay; delete el.dataset.navigationDisplay;
  }));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '导航测试页面不可横向越界');
  const showcase = page.getByTestId('showcase');
  await showcase.getByRole('button', { name: '下拉菜单', exact: true }).click();
  await showcase.getByRole('combobox', { name: '示例选项', exact: true }).click();
  assert.equal(await page.getByRole('option', { name: '暂不可选', exact: true }).isDisabled(), true);
  await page.keyboard.press('Escape');
  await showcase.getByRole('button', { name: '按钮与切换', exact: true }).click();
  const demo = showcase.getByRole('navigation', { name: '长文字页签演示', exact: true });
  await demo.getByRole('button').last().click();
  await fits(demo, `${width}/展示页长页签`);
  if (selfTest) {
    await demo.scrollIntoViewIfNeeded();
    const screenshot = join(tmpdir(), `nora-navigation-${width}-${process.pid}.png`);
    await page.screenshot({ path: screenshot });
    console.log(`导航展示页截图：${screenshot}`);
  }
  console.log(`导航检查：${width}px长选项、普通/分组/网格/滚动导航、菜单键盘禁用、分页边界与切换稳定性通过。`);
}
