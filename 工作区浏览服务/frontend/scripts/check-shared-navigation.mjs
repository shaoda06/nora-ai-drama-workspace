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
  const marked = fixture.getByTestId('nav-normal').getByRole('button', { name: '简短', exact: true });
  assert.equal(await marked.getAttribute('aria-description'), '本轮新生成视频');
  const dot = await marked.locator('.round-new-dot').evaluate(el => {
    const r = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
    return { width: r.width, height: r.height, top: r.top - parent.top, right: parent.right - r.right, color: getComputedStyle(el).backgroundColor };
  });
  assert.equal(dot.width, 7); assert.equal(dot.height, 7);
  assert.equal(dot.color, 'rgb(223, 146, 27)');
  assert.ok(dot.top >= 5 && dot.top <= 7 && dot.right >= 5 && dot.right <= 7, '黄点固定在按钮右上角内部');
  for (const label of ['短轮次下拉', '图标短选项']) {
    const combo = fixture.getByRole('combobox', { name: label, exact: true });
    await combo.click();
    const menu = page.getByRole('listbox', { name: label, exact: true });
    const selected = menu.getByRole('option', { selected: true });
    const bounds = await selected.evaluate(el => {
      const title = el.firstElementChild.getBoundingClientRect(), badge = el.lastElementChild.getBoundingClientRect();
      return { titleTop: title.top, titleBottom: title.bottom, badgeTop: badge.top, badgeBottom: badge.bottom, height: el.getBoundingClientRect().height };
    });
    assert.ok(bounds.badgeTop < bounds.titleBottom && bounds.badgeBottom > bounds.titleTop, `${width}/${label}: 当前标记不能另起一行`);
    assert.ok(Math.abs(bounds.height - (await menu.getByRole('option').last().boundingBox()).height) <= 1, '短选项的选中行与普通行应等高');
    await fits(menu, `${width}/${label}/菜单及当前标记`);
    await combo.press('Escape');
  }
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
      const comboBox = await combo.boundingBox();
      assert.ok(menuBox.width >= Math.min(comboBox.width, width - 16) - 1 && menuBox.width <= width - 16 + 1, '菜单以按钮宽度为最小值，由内容撑宽，只受屏幕限制');
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
  for (const count of [0, 1, 5, 6]) {
    const custom = fixture.getByTestId(`custom-pagination-${count}`);
    assert.equal(await custom.locator('.pagination > span').innerText(), '自定义选集内容', '单页保留自定义中间内容');
    assert.equal(await custom.getByRole('button').count(), count > 5 ? 2 : 0, '只有总数超过每页数量才显示翻页按钮');
    await fits(custom.locator('.pagination'), `${width}/自定义选集-${count}`);
  }
  const compact = filenames.locator('.pagination');
  assert.equal(await compact.locator(':scope > span').count(), 0, '自定义中间内容替代页码和总数');
  assert.equal(await compact.locator('nav > button').count(), 5);
  const layout = await compact.evaluate(el => ({ margin: getComputedStyle(el).marginTop, height: el.getBoundingClientRect().height,
    rows: [...el.querySelectorAll('nav > button')].map(button => button.getBoundingClientRect().top) }));
  assert.equal(layout.margin, '0px');
  assert.ok(layout.height < 110 && layout.rows.every(top => Math.abs(top - layout.rows[0]) < 1), '极窄容器翻页可换行，文件名仍保持单行');
  const pagerButtons = await compact.locator(':scope > button').evaluateAll(buttons => buttons.map(el => ({ width: el.getBoundingClientRect().width, padding: getComputedStyle(el).paddingLeft, scroll: el.scrollWidth, client: el.clientWidth })));
  assert.ok(pagerButtons.every(button => button.width >= 74 && button.padding === '14px' && button.scroll <= button.client + 1), '翻页文字保留正常宽度及左右内边距');
  assert.equal(await compact.evaluate(el => getComputedStyle(el).columnGap), '12px');
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
  for (const name of ['示例选项', '紧凑选项示例', '小号选项示例', '高亮选项示例', '表单选项示例']) {
    const combo = showcase.getByRole('combobox', { name, exact: true });
    await combo.click();
    const menu = page.getByRole('listbox', { name, exact: true });
    const triggerBox = await combo.boundingBox(), menuBox = await menu.boundingBox();
    assert.ok(menuBox.width >= Math.min(triggerBox.width, width - 16) - 1 && menuBox.width <= width - 16 + 1, `${name}菜单宽度随内容且不小于按钮`);
    await fits(menu, `${width}/${name}/长文字及当前标记`);
    assert.equal(await menu.getByRole('option', { name: '暂不可选', exact: true }).isDisabled(), true);
    if (name === '表单选项示例') {
      await page.setViewportSize({ width: width + 80, height: 918 });
      await page.waitForFunction(() => {
        const trigger = document.querySelector('[role=combobox][aria-label="表单选项示例"]').getBoundingClientRect();
        const menu = document.querySelector('[role=listbox][aria-label="表单选项示例"]').getBoundingClientRect();
        return menu.width >= Math.min(trigger.width, innerWidth - 16) - 1 && menu.left >= 8 && menu.right <= innerWidth - 8;
      });
      await page.setViewportSize({ width, height: 918 });
    }
    await menu.getByRole('option').last().click();
    await combo.click();
    await fits(menu, `${width}/${name}/选中长项`);
    const currentRow = await menu.getByRole('option', { selected: true }).evaluate(el => {
      const title = el.firstElementChild.getBoundingClientRect(), badge = el.lastElementChild.getBoundingClientRect();
      return { titleTop: title.top, titleBottom: title.bottom, badgeTop: badge.top, badgeBottom: badge.bottom, badgeHeight: badge.height };
    });
    assert.ok(currentRow.badgeTop < currentRow.titleBottom && currentRow.badgeBottom > currentRow.titleTop && currentRow.badgeHeight < 30, `${name}: 长文字可换行，当前标记仍在右侧同一行`);
    await combo.press('Escape');
  }
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
