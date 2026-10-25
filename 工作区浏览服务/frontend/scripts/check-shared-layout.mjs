import { checkEpisodeDirectorSheets } from './check-episode-director-sheets.mjs';
import { checkSharedInputs } from './check-shared-inputs.mjs';
import { checkSharedPlayback } from './check-shared-playback.mjs';
import { checkSharedNavigation } from './check-shared-navigation.mjs';
import assert from 'node:assert/strict';
import { checkSharedFeedback } from './check-shared-feedback.mjs';
import { execFileSync } from 'node:child_process';
import { mkdtemp, realpath, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, preview } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';

// Always build the Git index, never the working tree or an already-running service.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: frontend, encoding: 'utf8' }).trim();
const prefix = '工作区浏览服务/frontend/';
const temp = await realpath(await mkdtemp(join(tmpdir(), 'nora-shared-layout-')));
const root = join(temp, prefix);
let server, browser;
const selfTest = process.argv.includes('--self-test');
const styleOf = locator => locator.evaluate(el => {
  const style = getComputedStyle(el);
  return Object.fromEntries(['fontSize', 'lineHeight', 'padding', 'height', 'borderRadius'].map(key => [key, style[key]]));
});
async function sameStyle(locator, expected, context) {
  assert.deepEqual(await styleOf(locator), expected, `[字号/样式继承] ${context} 与展示页同规格不同`);
}
async function contained(locator, context) {
  const bounds = await locator.evaluate(el => {
    const own = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
    return { left: own.left, right: own.right, parentLeft: parent.left, parentRight: parent.right,
      children: [...el.children].filter(child => child.getClientRects().length).map(child => { const r = child.getBoundingClientRect(); return { left: r.left, right: r.right }; }) };
  });
  assert.ok(bounds.left >= bounds.parentLeft - 1 && bounds.right <= bounds.parentRight + 1
    && bounds.children.every(child => child.left >= bounds.left - 1 && child.right <= bounds.right + 1),
  `[容器越界] ${context}: ${JSON.stringify(bounds)}`);
}
try {
  const files = execFileSync('git', ['ls-files', '-z', '--', prefix], { cwd: repo, encoding: 'utf8' });
  execFileSync('git', ['checkout-index', '-z', '--stdin', `--prefix=${temp}/`], { cwd: repo, input: files });
  await symlink(join(frontend, 'node_modules'), join(root, 'node_modules'), 'junction');
  const config = { root, configFile: false, plugins: [react()], logLevel: 'error',
    define: { __APP_VERSION__: JSON.stringify('layout-check') },
    build: { outDir: 'layout-dist', rollupOptions: { input: join(root, 'tests/shared-layout/index.html') } } };
  await build(config);
  server = await preview({ ...config, preview: { host: '127.0.0.1', port: 0, open: false } });
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  for (const width of [1362, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 918 } });
    const errors = [], forbidden = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin || url.pathname.startsWith('/api/') || !['GET', 'HEAD'].includes(request.method())) {
        forbidden.push(request.url()); return route.abort();
      }
      return route.continue();
    });
    await page.goto(origin + '/tests/shared-layout/index.html');
    assert.equal(await page.title(), '公共组件布局自动检查');
    await checkSharedInputs(page, width, selfTest);
    const showcase = page.getByTestId('showcase'), business = page.getByTestId('business');
    await showcase.getByRole('button', { name: '下拉菜单', exact: true }).click();
    const reference = showcase.getByRole('combobox', { name: '高亮选项示例', exact: true });
    const expected = await styleOf(reference);
    const selectors = business.locator('.segment-selectors');
    for (const wide of [false, true]) {
      if (wide) await business.getByRole('button', { name: '宽屏显示', exact: true }).click();
      for (const candidate of ['候选一', '候选二']) {
        const candidateSelect = business.getByRole('combobox', { name: '版本切换', exact: true });
        await candidateSelect.click();
        const menu = page.getByRole('listbox', { name: '版本切换', exact: true });
        // Popovers intentionally escape their parents; constrain them to the viewport instead.
        const menuBounds = await menu.boundingBox();
        assert.ok(menuBounds.x >= 0 && menuBounds.x + menuBounds.width <= width, '[菜单越界]');
        await menu.getByRole('option', { name: new RegExp(candidate) }).click();
        const context = `${width}px / ${wide ? '宽屏' : '普通'} / ${candidate}`;
        for (const name of ['画质选择', '版本切换']) await sameStyle(business.getByRole('combobox', { name, exact: true }), expected, `${context} / ${name}`);
        await contained(selectors, context);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        assert.equal(overflow, false, `[页面越界] ${context}`);
      }
    }
    if (selfTest && width === 390) {
      // Inject each known failure, then run the very same assertions used above.
      let injected = await page.addStyleTag({ content: '.video-source{font-size:11px!important}.segment-selectors .tab-select{font-size:inherit!important}' });
      await assert.rejects(sameStyle(business.getByRole('combobox', { name: '画质选择', exact: true }), expected, '模拟宽屏继承'), /字号\/样式继承/);
      await injected.evaluate(el => el.remove());
      injected = await page.addStyleTag({ content: '.segment-selectors{max-width:none!important;flex-wrap:nowrap!important}' });
      await assert.rejects(contained(selectors, '模拟手机越界'), /容器越界/);
      await injected.evaluate(el => el.remove());
      await contained(selectors, '恢复后');
      const screenshot = join(tmpdir(), `nora-shared-layout-${process.pid}.png`);
      await selectors.scrollIntoViewIfNeeded();
      await page.screenshot({ path: screenshot });
      console.log(`反向验证：模拟字号继承、容器越界均被拦截，恢复后通过。截图：${screenshot}`);
    }
    await checkSharedFeedback(page, width, selfTest);
    const sheets = page.getByTestId('director-sheets');
    const sheetImage = sheets.locator('.director-sheet-image img');
    const sheetArrows = sheets.locator('.pagination-arrows');
    assert.equal(await sheets.locator('.director-sheet-page-count').count(), 0, '不再显示底部页数');
    const directorGap = await sheets.locator('.director-sheet-toolbar').evaluate(el =>
      el.getBoundingClientRect().top - el.closest('.episode-scene-content').getBoundingClientRect().top);
    assert.equal(directorGap, 21, '标签栏后只保留内容区20px内边距及1px分隔线，不叠加工具栏外边距');
    assert.equal(await sheetImage.count(), 1, '导演表每次仅显示一张大图');
    const originalLink = sheets.getByRole('link', { name: '查看原图 ↗', exact: true });
    const downloadLink = sheets.getByRole('link', { name: '下载原图', exact: true });
    assert.equal(await originalLink.count(), 0);
    assert.equal(await downloadLink.count(), 1);
    assert.match(await downloadLink.getAttribute('href'), /download=true/);
    await contained(sheets.locator('.director-sheet-record'), `${width}px / 记录与下载入口`);
    const recordBounds = await sheets.getByRole('button', { name: '查看记录', exact: true }).boundingBox();
    const downloadBounds = await downloadLink.boundingBox();
    assert.ok(downloadBounds.x >= recordBounds.x + recordBounds.width, '下载位于记录右侧');
    assert.ok(Math.abs(downloadBounds.y + downloadBounds.height / 2 - recordBounds.y - recordBounds.height / 2) < 2, '记录与下载同排居中');
    assert.equal(await sheets.locator('.director-sheet-footer').count(), 0, '图片底部不再放下载行');

    const sheetPages = sheets.getByRole('navigation', { name: '导演分镜表页码' });
    assert.equal(await sheetPages.getByRole('button').count(), 3);
    await sheetPages.getByRole('button', { name: '3', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /第03页/);
    assert.equal(await sheetPages.getByRole('button', { name: '3', exact: true }).getAttribute('aria-current'), 'page');
    await sheetPages.getByRole('button', { name: '1', exact: true }).click();
    await contained(sheetPages, `${width}px / 导演表数字页码`);
    const pageCenter = await sheetPages.boundingBox();
    const toolbarCenter = await sheets.locator('.director-sheet-toolbar').boundingBox();
    assert.ok(Math.abs(pageCenter.x + pageCenter.width / 2 - toolbarCenter.x - toolbarCenter.width / 2) < 1, '数字页码相对整条工具栏居中');
    assert.equal(await sheets.locator('.director-sheet-source').count(), 0, '本场不显示重复来源版本文字');
    assert.equal(await sheets.getByText(/当前已采用的正式图片|点击图片可放大查看/).count(), 0, '移除说明文字');
    assert.equal(await sheets.locator('.pagination').count(), 0, '底部不重复放翻页按钮');
    assert.equal(await sheetArrows.getByRole('button', { name: '上一张图', exact: true }).count(), 0, '首张隐藏上一张');
    const arrowCircle = await sheetArrows.getByRole('button', { name: '下一张图', exact: true }).evaluate(el => {
      const box = el.getBoundingClientRect(), style = getComputedStyle(el), frame = el.parentElement.getBoundingClientRect();
      return { width: box.width, height: box.height, radius: style.borderRadius, rightGap: frame.right - box.right };
    });
    assert.deepEqual(arrowCircle, { width: 40, height: 40, radius: '50%', rightGap: 12 }, '圆形右箭头固定在图片右侧');
    await sheetArrows.getByRole('button', { name: '下一张图', exact: true }).click();
    assert.equal(await sheetPages.getByRole('button', { name: '2', exact: true }).getAttribute('aria-current'), 'page', '箭头同步顶部页码');
    await sheetArrows.getByRole('button', { name: '下一张图', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /第03页/);
    assert.equal(await sheetArrows.getByRole('button', { name: '下一张图', exact: true }).count(), 0, '末张隐藏下一张');
    await sheetArrows.getByRole('button', { name: '上一张图', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /第02页/);
    assert.equal(await sheetPages.getByRole('button', { name: '2', exact: true }).getAttribute('aria-current'), 'page');
    await sheets.getByRole('button', { name: '全屏查看第02页导演分镜表', exact: true }).click();
    const sheetDialog = page.getByRole('dialog');
    await sheetDialog.waitFor({ state: 'visible' });
    assert.match(await sheetDialog.getAttribute('class'), /dialog-fullscreen/);
    assert.equal(await sheetDialog.locator(':scope > header').count(), 0, '全屏看图不显示顶部栏');
    const fullscreenBox = await sheetDialog.boundingBox();
    assert.equal(fullscreenBox.x, 0);
    assert.equal(fullscreenBox.y, 0);
    assert.equal(fullscreenBox.width, width);
    assert.equal(fullscreenBox.height, 918);
    const fullscreenStyle = await sheetDialog.evaluate(el => ({ background: getComputedStyle(el).backgroundColor, padding: getComputedStyle(el.querySelector('.dialog-body')).padding }));
    assert.equal(fullscreenStyle.background, 'rgba(24, 34, 47, 0.9)', '深灰蓝半透明蒙版');
    const imageFrame = await sheetDialog.locator('.director-sheet-fullscreen-image').boundingBox();
    assert.ok(imageFrame.x >= 16 && imageFrame.y >= 48 && imageFrame.x + imageFrame.width <= width - 16 && imageFrame.y + imageFrame.height <= 918 - 24, '全屏图像四周留空隙');
    const closeCircle = await sheetDialog.getByRole('button', { name: '关闭', exact: true }).boundingBox();
    assert.equal(closeCircle.width, 40);
    assert.equal(closeCircle.height, 40);
    assert.equal(closeCircle.y, 12);
    assert.equal(closeCircle.x + closeCircle.width, width - 16);
    assert.match(await sheetDialog.locator('.director-sheet-fullscreen-image > img').getAttribute('alt'), /第02页/);
    await sheetDialog.getByRole('button', { name: '下一张图', exact: true }).click();
    assert.match(await sheetDialog.locator('.director-sheet-fullscreen-image > img').getAttribute('alt'), /第03页/);
    await page.keyboard.press('Escape');
    await sheetDialog.waitFor({ state: 'hidden' });
    assert.match(await sheetImage.getAttribute('alt'), /第03页/, '退出全屏保留当前页');
    await sheets.getByRole('button', { name: '全屏查看第03页导演分镜表', exact: true }).click();
    await sheetDialog.getByRole('button', { name: '退出全屏看图', exact: true }).click();
    await sheetDialog.waitFor({ state: 'hidden' });
    await sheets.getByRole('button', { name: '全屏查看第03页导演分镜表', exact: true }).click();
    await sheetDialog.getByRole('button', { name: '关闭', exact: true }).click();
    await sheetDialog.waitFor({ state: 'hidden' });
    assert.match(await sheetImage.getAttribute('alt'), /第03页/, '叉号退出保留当前页');
    const sheetVersion = sheets.getByRole('combobox', { name: '导演分镜表候选' });
    assert.match(await sheetVersion.innerText(), /候选2.*已采用/s);
    assert.equal(await sheets.getByRole('combobox', { name: '导演分镜表版本' }).count(), 0, '取消独立已采用版本');
    const recordBox = await sheets.locator('.director-sheet-record').boundingBox();
    const toolbarBox = await sheets.locator('.director-sheet-toolbar').boundingBox();
    assert.ok(Math.abs(recordBox.x + recordBox.width - toolbarBox.x - toolbarBox.width) < 2, '审阅记录靠右');
    await sheets.getByRole('button', { name: '查看记录', exact: true }).click();
    await sheetDialog.waitFor({ state: 'visible' });
    assert.equal(await sheetDialog.getByText('隔离示例审阅记录', { exact: true }).count(), 1);
    await sheetDialog.getByRole('button', { name: '关闭', exact: true }).click();
    await sheetVersion.click();
    await page.getByRole('option', { name: '候选1（2张）', exact: true }).click();
    assert.equal(await sheetImage.count(), 1, '候选也逐页显示');
    assert.match(await sheetImage.getAttribute('alt'), /v01-第01页/, '切换版本回到本组第一页');
    await sheetArrows.getByRole('button', { name: '下一张图', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /v01-第03页/);
    await contained(sheets.locator('.director-sheet-image'), `${width}px / 导演表单页`);
    await contained(sheetArrows, `${width}px / 图片左右箭头`);
    assert.equal(await sheetPages.getByRole('button', { name: '2', exact: true }).getAttribute('aria-current'), 'page', '缺页候选按阅读顺序显示，仍定位实际图片页号');
    await sheets.getByRole('button', { name: '模拟七页候选', exact: true }).click();
    assert.deepEqual(await sheetPages.getByRole('button').allTextContents(), ['1', '2', '3', '4', '5', '6', '7']);
    await sheetPages.getByRole('button', { name: '7', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /第07页/);
    assert.equal(await sheetPages.getByRole('button', { name: '7', exact: true }).getAttribute('aria-current'), 'page');
    await sheetArrows.getByRole('button', { name: '上一张图', exact: true }).click();
    assert.equal(await sheetPages.getByRole('button', { name: '6', exact: true }).getAttribute('aria-current'), 'page');
    await contained(sheets.locator('.director-sheet-pages'), `${width}px / 七页候选数字选择容器`);
    assert.equal(await sheetPages.evaluate(el => getComputedStyle(el).overflowX), 'auto', '窄屏页码只在自身横向滚动');
    const sevenCenter = await sheets.locator('.director-sheet-pages').boundingBox();
    const sevenToolbar = await sheets.locator('.director-sheet-toolbar').boundingBox();
    assert.ok(Math.abs(sevenCenter.x + sevenCenter.width / 2 - sevenToolbar.x - sevenToolbar.width / 2) < 1, '七页组在桌面及窄屏工具栏中居中');
    const selectedPageBounds = await sheetPages.evaluate(el => {
      const box = el.getBoundingClientRect(), current = el.querySelector('[aria-current="page"]').getBoundingClientRect();
      return { left: box.left, right: box.right, selectedLeft: current.left, selectedRight: current.right };
    });
    assert.ok(selectedPageBounds.selectedLeft >= selectedPageBounds.left - 1 && selectedPageBounds.selectedRight <= selectedPageBounds.right + 1, '直接选择后的当前页在滚动区域可见');
    await sheets.getByRole('button', { name: '模拟仅候选', exact: true }).click();
    assert.match(await sheets.getByRole('combobox', { name: '导演分镜表候选' }).innerText(), /候选2/);
    assert.equal(await sheetImage.count(), 1, '无采用时默认当前来源最新候选');
    await sheets.getByRole('button', { name: '模拟无图旧版分镜', exact: true }).click();
    assert.equal(await sheets.getByText('分镜 v01 尚未制作导演分镜表。', { exact: true }).count(), 1);
    assert.equal(await sheetImage.count(), 0, '旧分镜不换用新图');
    await sheets.getByRole('button', { name: '模拟其他来源分镜', exact: true }).click();
    assert.match(await sheetImage.getAttribute('alt'), /v03-第01页/, '仅显示匹配来源候选');
    assert.equal(await sheetPages.getByRole('button').count(), 1);
    assert.equal(await sheetArrows.count(), 0, '单页不出现翻页箭头');
    await sheets.getByRole('button', { name: '模拟空场次', exact: true }).click();
    assert.equal(await sheets.getByText('分镜 v07 尚未制作导演分镜表。', { exact: true }).count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '导演表手机无横向溢出');
    await checkEpisodeDirectorSheets(page, sheets, width);
    console.log(`导演分镜表检查：${width}px单图、移除重复版本文字、数字跳页与高亮同步、圆形箭头、首尾隐藏、记录与下载同排靠右、全视口看图与退出、审阅入口靠右、来源版本筛选、候选采用状态、单页及空场次通过。`);
    await showcase.getByRole('button', { name: '列表与分页', exact: true }).click();
    const sheetPagination = showcase.locator('.pagination').last();
    await sheetPagination.getByRole('button', { name: '下一页', exact: true }).click();
    assert.match(await sheetPagination.innerText(), /第2页 \/ 共\d+页/);
    await contained(sheetPagination, `${width}px / 展示页逐页阅读分页`);
    const exampleArrows = showcase.locator('.pagination-arrows');
    await exampleArrows.getByRole('button', { name: '下一张图', exact: true }).click();
    assert.match(await sheetPagination.innerText(), /第3页 \/ 共3页/);
    assert.equal(await exampleArrows.getByRole('button', { name: '下一张图', exact: true }).count(), 0);
    await contained(exampleArrows, `${width}px / 展示页箭头`);
    await showcase.getByRole('button', { name: '弹窗与阅读', exact: true }).click();
    await showcase.getByRole('button', { name: '打开全屏示例', exact: true }).click();
    const fullExample = page.getByRole('dialog');
    assert.match(await fullExample.getAttribute('class'), /dialog-fullscreen/);
    assert.equal(await fullExample.locator(':scope > header').count(), 0, '展示页使用真实无顶部栏规格');
    assert.equal((await fullExample.boundingBox()).width, width);
    await fullExample.getByRole('button', { name: '关闭', exact: true }).click();
    await showcase.getByRole('button', { name: '文件与正文', exact: true }).click();
    assert.equal(await showcase.getByRole('link', { name: '查看原图 ↗', exact: true }).count(), 1);
    assert.equal(await showcase.getByRole('link', { name: '下载原图', exact: true }).count(), 1);
    await checkSharedNavigation(page, width, selfTest);
    await checkSharedPlayback(page, width);
    assert.deepEqual(forbidden, [], '测试不得访问API、外部网络或写入业务');
    assert.deepEqual(errors, [], '浏览器错误');
    console.log(`公共组件布局检查：${width}px普通/宽屏、最新/旧候选、展示页同规格样式、父容器及菜单边界通过。`);
    await page.close();
  }
} finally {
  if (browser) await browser.close();
  if (server) await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  await rm(temp, { recursive: true, force: true });
}
