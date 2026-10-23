import assert from 'node:assert/strict';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

async function fieldFits(field, context) {
  const r = await field.evaluate(el => {
    const box = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
    return { x: box.x, right: box.right, parentX: parent.x, parentRight: parent.right, viewport: innerWidth,
      textarea: el.tagName === 'TEXTAREA', contentWidth: el.scrollWidth, width: el.clientWidth };
  });
  assert.ok(r.x >= r.parentX - 1 && r.right <= r.parentRight + 1 && r.x >= 0 && r.right <= r.viewport
    && (!r.textarea || r.contentWidth <= r.width + 1), `[输入边界] ${context}: ${JSON.stringify(r)}`);
}
async function switchFits(control, context) {
  const r = await control.evaluate(el => {
    const box = el.getBoundingClientRect(), thumb = el.firstElementChild.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
    return { width: box.width, height: box.height, thumbWidth: thumb.width, thumbHeight: thumb.height,
      contained: box.left >= parent.left && box.right <= parent.right + 1 && thumb.left >= box.left && thumb.right <= box.right && thumb.top >= box.top && thumb.bottom <= box.bottom };
  });
  assert.ok(r.width === 38 && r.height === 22 && r.thumbWidth === 16 && r.thumbHeight === 16 && r.contained,
    `[开关挤压] ${context}: ${JSON.stringify(r)}`);
}
export async function checkSharedInputs(page, width, selfTest) {
  const fixture = page.getByTestId('inputs');
  const counts = async () => JSON.parse(await fixture.getByTestId('input-counts').innerText());
  const longValue = '中文搜索、标题与正文输入' + 'LongUnbrokenInputValue'.repeat(20);
  for (const name of ['标准搜索检查', '紧凑搜索检查', '单行输入检查', '多行输入检查']) {
    const field = fixture.getByLabel(name, { exact: true });
    await field.scrollIntoViewIfNeeded();
    await fieldFits(field, `${width}/${name}/长占位`);
    const initialBox = await field.boundingBox();
    await field.fill(longValue);
    assert.equal(await fixture.getByLabel('多行输入检查', { exact: true }).inputValue(), longValue, '输入应同步到受控状态');
    const filledBox = await field.boundingBox();
    assert.ok(Math.abs(initialBox.width - filledBox.width) <= 1 && Math.abs(initialBox.height - filledBox.height) <= 1, '长输入不改变控件外框');
    assert.equal(await field.inputValue(), longValue);
    await fieldFits(field, `${width}/${name}/长输入`);
    await field.press('End'); await page.keyboard.insertText('新增中文');
    assert.equal(await field.inputValue(), longValue + '新增中文');
    if (name === '多行输入检查') {
      await field.press('Enter'); await page.keyboard.insertText('第二行正文');
      assert.equal(await field.inputValue(), longValue + '新增中文\n第二行正文');
      assert.equal((await counts()).submits, 0, '多行回车不提交表单');
      await fieldFits(field, `${width}/多行换行`);
    }
    const beforeClear = (await counts()).changes;
    await field.press('ControlOrMeta+a'); await field.press('Backspace');
    assert.equal(await field.inputValue(), '');
    assert.ok((await counts()).changes > beforeClear, '清空应同步受控状态');
  }
  for (const name of ['只读输入检查', '只读多行检查']) {
    const field = fixture.getByLabel(name, { exact: true }); const value = await field.inputValue();
    assert.equal(await field.isEditable(), false);
    await field.focus(); await field.press('ControlOrMeta+a'); await field.press('Backspace');
    await page.keyboard.insertText('不能写入');
    assert.equal(await field.inputValue(), value, '只读输入不得更改');
    await fieldFits(field, `${width}/${name}`);
  }
  const control = fixture.getByRole('switch');
  await control.scrollIntoViewIfNeeded();
  await switchFits(control, `${width}/长标签关闭态`);
  const initial = await counts();
  for (const action of ['click', 'Space', 'Enter']) {
    const before = await counts();
    if (action === 'click') await control.click(); else await control.press(action);
    const after = await counts();
    assert.equal(after.checked, !before.checked, `${action}切换一次`);
    assert.equal(after.toggles, before.toggles + 1);
    assert.equal(after.submits, initial.submits, '开关不得隐式提交表单');
    assert.equal(await control.getAttribute('aria-checked'), String(after.checked));
    await switchFits(control, `${width}/${action}`);
  }
  const single = fixture.getByLabel('单行输入检查', { exact: true });
  await single.fill('禁用前保留内容');
  await fixture.getByRole('button', { name: '切换输入禁用', exact: true }).click();
  const disabledState = await counts();
  for (const field of await fixture.locator('input:not([readonly]),textarea:not([readonly])').all()) {
    assert.equal(await field.isDisabled(), true); assert.equal(await field.isEditable(), false);
    await field.click({ force: true }); await page.keyboard.insertText('不应改变');
    assert.equal(await field.inputValue(), '禁用前保留内容');
  }
  assert.equal(await control.isDisabled(), true);
  await control.click({ force: true });
  assert.deepEqual(await counts(), disabledState, '禁用控件不触发输入/切换回调');
  await fixture.getByRole('button', { name: '切换输入禁用', exact: true }).focus();
  await page.keyboard.press('Tab');
  assert.equal(await fixture.getByLabel('只读输入检查', { exact: true }).evaluate(el => el === document.activeElement), true, 'Tab跳过禁用控件');
  await fixture.getByRole('button', { name: '切换输入禁用', exact: true }).click();
  await single.fill('重新启用'); assert.equal(await single.inputValue(), '重新启用');
  await control.click(); assert.equal((await counts()).toggles, disabledState.toggles + 1);
  await fixture.getByRole('button', { name: '提交示例输入', exact: true }).click();
  assert.equal((await counts()).submits, 1);
  if (selfTest && width === 390) {
    let injected = await page.addStyleTag({ content: '.search-field{min-width:600px!important}' });
    await assert.rejects(fieldFits(fixture.getByLabel('标准搜索检查', { exact: true }), '模拟搜索越界'), /输入边界/);
    await injected.evaluate(el => el.remove());
    injected = await page.addStyleTag({ content: '.ui-switch{width:12px!important;min-width:0!important}' });
    await assert.rejects(switchFits(control, '模拟开关挤压'), /开关挤压/);
    await injected.evaluate(el => el.remove());
    await switchFits(control, '恢复开关');
    console.log('反向验证：输入框越界、开关挤压均被拦截，恢复后通过。');
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth ? [...document.querySelectorAll('input, textarea, output, [role=switch]')].filter(el => el.getBoundingClientRect().right > innerWidth).map(el => ({ tag: el.tagName, name: el.getAttribute('aria-label'), right: el.getBoundingClientRect().right })) : []);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `输入测试页面不可横向越界：${JSON.stringify(overflow)}`);
  const showcase = page.getByTestId('showcase');
  await showcase.getByRole('button', { name: '按钮与切换', exact: true }).click();
  await showcase.getByRole('button', { name: '填入长文字', exact: true }).click();
  for (const name of ['单行输入示例', '多行输入示例', '只读输入示例']) await fieldFits(showcase.getByLabel(name, { exact: true }), `${width}/展示/${name}`);
  await switchFits(showcase.getByRole('switch', { name: '长说明开关示例', exact: true }), `${width}/展示开关`);
  await showcase.getByRole('switch', { name: '禁用输入示例', exact: true }).click();
  assert.equal(await showcase.getByLabel('单行输入示例', { exact: true }).isDisabled(), true);
  await showcase.getByRole('switch', { name: '禁用输入示例', exact: true }).click();
  await showcase.getByRole('button', { name: '布局与搜索', exact: true }).click();
  await showcase.getByRole('button', { name: '填入长搜索文字', exact: true }).click();
  for (const name of ['搜索示例入口', '紧凑搜索示例']) await fieldFits(showcase.getByRole('searchbox', { name, exact: true }), `${width}/展示/${name}`);
  assert.equal(await showcase.getByRole('searchbox', { name: '禁用搜索示例', exact: true }).isDisabled(), true);
  if (selfTest) {
    await fixture.getByTestId('input-container').scrollIntoViewIfNeeded();
    const screenshot = join(tmpdir(), `nora-inputs-${width}-${process.pid}.png`);
    await page.screenshot({ path: screenshot }); console.log(`输入组件截图：${screenshot}`);
  }
  console.log(`输入检查：${width}px标准/紧凑搜索、单行/多行输入长文字及只读禁用、清空重输、开关鼠标/键盘切换和禁用跳过通过。`);
}
