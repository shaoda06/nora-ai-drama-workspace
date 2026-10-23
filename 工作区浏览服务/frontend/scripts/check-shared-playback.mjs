import assert from 'node:assert/strict';

export async function checkSharedPlayback(page, width) {
  const business = page.getByTestId('business');
  const showcase = page.getByTestId('showcase');
  await showcase.getByRole('button', { name: '图片与音视频', exact: true }).click();
  const demo = showcase.getByRole('region', { name: '分段播放器', exact: true });
  for (const area of [business, demo]) {
    const repeat = area.getByRole('checkbox', { name: '重复播放', exact: true });
    const continuous = area.getByRole('checkbox', { name: '连续播放', exact: true });
    const video = area.locator('.segment-video video');
    assert.equal(await repeat.isChecked(), false);
    assert.equal(await video.evaluate(el => el.loop), false);
    for (const wide of [false, true]) {
      const toggle = area.getByRole('button', { name: wide ? '宽屏显示' : '恢复布局', exact: true });
      if (await toggle.count()) await toggle.click();
      await video.evaluate(el => el.pause());
      const before = await video.evaluate(el => el.currentTime);
      await repeat.check();
      assert.equal(await video.evaluate(el => el.loop), true);
      assert.equal(await video.evaluate(el => el.paused), true, '勾选不自动开播');
      assert.equal(await video.evaluate(el => el.currentTime), before, '勾选不重置播放位置');
      const controls = area.locator('.video-source-actions');
      assert.deepEqual(await controls.getByRole('checkbox').evaluateAll(els => els.map(el => el.parentElement.textContent)), ['重复播放', '连续播放']);
      const box = await controls.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width + 1, '播放开关不越界');
      await continuous.check();
      assert.equal(await repeat.isChecked(), false);
      assert.equal(await repeat.isDisabled(), true);
      assert.equal(await video.evaluate(el => el.loop), false);
      await continuous.uncheck();
      assert.equal(await repeat.isDisabled(), false);
      assert.equal(await repeat.isChecked(), false, '关闭连续播放不恢复重复播放');
      await repeat.focus(); await page.keyboard.press('Space');
      assert.equal(await repeat.isChecked(), true, '键盘可开启重复播放');
      await repeat.uncheck();
    }
  }
  const video = business.locator('.segment-video video');
  const repeat = business.getByRole('checkbox', { name: '重复播放', exact: true });
  await video.evaluate(async el => {
    if (el.readyState < 1) await new Promise(resolve => el.addEventListener('loadedmetadata', resolve, { once: true }));
    el.muted = true;
  });
  const endedBefore = await business.getByRole('status', { name: '播放结束次数' }).innerText();
  await repeat.check();
  await video.evaluate(async el => { el.currentTime = el.duration - 0.15; await el.play(); });
  await page.waitForFunction(() => {
    const video = document.querySelector('[data-testid="business"] .segment-video video');
    return video.currentTime > 0.05 && video.currentTime < video.duration - 0.3 && !video.paused;
  });
  assert.equal(await business.getByRole('status', { name: '播放结束次数' }).innerText(), endedBefore, '循环不触发分段推进');
  await video.evaluate(el => el.pause());
  await repeat.uncheck();
  await video.evaluate(async el => { el.currentTime = el.duration - 0.15; await el.play(); });
  await page.waitForFunction(() => document.querySelector('[data-testid="business"] .segment-video video').ended);
  assert.equal(Number(await business.getByRole('status', { name: '播放结束次数' }).innerText()), Number(endedBefore) + 1, '未循环时保留结束回调');
  await repeat.check();
  const candidate = business.getByRole('combobox', { name: '版本切换', exact: true });
  await candidate.click();
  await page.getByRole('listbox', { name: '版本切换', exact: true }).getByRole('option', { name: /候选一/ }).click();
  assert.equal(await repeat.isChecked(), false, '更换视频版本重置重复播放');
  await business.getByRole('combobox', { name: '画质选择', exact: true }).click();
  await page.getByRole('listbox', { name: '画质选择', exact: true }).getByRole('option', { name: '二采', exact: true }).click();
  assert.equal(await repeat.isDisabled(), true, '无视频不可开启重复播放');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '空视频时操作行不撑宽页面');
  console.log(`重复播放检查：${width}px制作页与真实展示普通／宽屏、鼠标键盘、连续播放互斥、真实视频循环／结束、版本重置及空视频禁用通过。`);
}
