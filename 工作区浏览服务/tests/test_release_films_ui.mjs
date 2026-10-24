// Real Project, ReleaseFilms, TabNav and Pagination; all API responses are local fixtures.
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
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-release-films-'));
const sample = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const file = (name, parent = '') => ({ kind: 'video', name, key: `98-发布成片/${parent}${name}`,
  url: '/api/projects/fixture/files/' + encodeURIComponent(`98-发布成片/${parent}${name}`) });
const rootFile = file('第1集.webm');
const longFile = file('第12集-' + '中文长名称与LongUnbrokenReference'.repeat(5) + '.webm', '子目录/');
const episodes = Array.from({ length: 10 }, (_, index) => file(`第${index + 1}集.webm`)).reverse();
const intro = file('片头.webm', '靠后目录/'), outro = file('片尾.webm', '子目录/');
const tree = { kind: 'group', name: '发布成片', key: '98-发布成片', note: '只读浏览，不修改用户文件。', children: [rootFile,
  ...episodes.filter(item => item.name !== rootFile.name),
  { kind: 'group', name: '子目录', children: [file('第11集.webm', '子目录/'), longFile] },
  { kind: 'group', name: '待导出空目录', children: [] },
  { kind: 'text', name: '说明.txt', key: '98-发布成片/说明.txt' }] };
let mode = 'files', navigation = 'release', failDownload = false, unexpected = [], writes = [];
// Serve downloads over real local HTTP; browser route interception cannot reliably complete attachments.
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)),
  define: { __APP_VERSION__: JSON.stringify('release-fixture') }, server: { host: '127.0.0.1', port: 0 },
  plugins: [react(), { name: 'read-only-release-fixture', configureServer(vite) {
    vite.middlewares.use((request, response, next) => {
      const url = new URL(request.url, 'http://fixture.invalid'), pathname = decodeURIComponent(url.pathname);
      if (!pathname.startsWith('/api/')) return next();
      if (request.method !== 'GET') { writes.push(request.url); response.writeHead(405); return response.end(); }
      let data;
      if (pathname.includes('/files/')) {
        if (failDownload && request.headers['sec-fetch-dest'] === 'empty') { response.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' }); return response.end('示例下载失败'); }
        response.setHeader('Content-Type', 'video/webm');
        if (url.searchParams.has('download')) response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(rootFile.name)}`);
        return response.end(sample);
      }
      if (pathname.endsWith('/status')) data = { revision: 1, updating: false, checking: false };
      else if (pathname.endsWith('/overview')) data = { project: '发布目录示例', active: [], warnings: [], directories: [
        { name: '00-项目定位', label: '项目定位' }, { name: '09-剧集制作', label: '剧集制作' },
        ...(navigation !== 'none' && navigation !== 'account' ? [{ name: '98-发布成片', label: '发布成片' }] : []),
        { name: '08-参考视频', label: '参考视频' },
        ...(navigation === 'full' ? [{ name: '11-社交媒体资料', label: '账号资料' }, { name: '10-封面资料', label: '封面资料' },
          { name: '03-人物资料', label: '人物资料' }, { name: '04-场景资料', label: '场景资料' }, { name: '05-道具资料', label: '道具资料' },
          { name: '07-参考音频', label: '参考音频' }] : navigation === 'account' ? [{ name: '11-社交媒体资料', label: '账号资料' }] : [])] };
      else if (pathname.endsWith('/sections/00-项目定位')) data = { kind: 'group', children: [
        { ...rootFile, statusHtml: '<span class="status-badge status-green">已确认</span>' },
        { kind: 'group', name: '通用目录', children: [longFile] }] };
      else if (pathname.endsWith('/sections/98-发布成片')) {
        if (mode === 'error') { response.statusCode = 503; data = { detail: '本地模拟读取失败' }; }
        else data = { ...tree, children: mode === 'empty' ? [] : mode === 'single' ? [rootFile] : mode === 'priority' ? [
          ...tree.children, { kind: 'group', name: '靠后目录', children: [intro] },
          { kind: 'group', name: '片尾目录', children: [outro] },
        ] : tree.children };
      } else if (/\/sections\/(03-人物资料|04-场景资料|05-道具资料|07-参考音频|10-封面资料|11-社交媒体资料)$/.test(pathname)) data = { exists: false, groups: [] };
      else { unexpected.push(pathname); response.statusCode = 404; data = {}; }
      response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(data));
    });
  } }],
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage(), errors = [];
    mode = 'files'; navigation = 'release'; failDownload = false; unexpected = []; writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error' && !message.text().includes('503 (Service Unavailable)')) errors.push(message.text()); });
    await page.goto(base + '/tests/release-films.html');
    assert.equal(await page.title(), '发布成片只读浏览检查');
    const generic = page.locator('section.panel:not([hidden])');
    await generic.getByText('已确认', { exact: true }).waitFor();
    await generic.locator('summary').filter({ hasText: '通用目录' }).click();
    await generic.getByText('未知', { exact: true }).waitFor();
    assert.equal(await generic.getByRole('link', { name: '下载', exact: true }).count(), 2, '通用文件树默认状态及操作保持');
    const entry = page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('combobox', { name: '发布资料', exact: true });
    const openRelease = async () => { await entry.click(); await page.getByRole('option', { name: /^发布成片(?:\s+当前)?$/ }).click(); };
    await openRelease();
    const panel = page.locator('section.panel:not([hidden])');
    const selector = panel.getByRole('navigation', { name: '发布成片选集', exact: true });
    await selector.getByRole('button', { name: '第1集', exact: true }).waitFor();
    assert.equal(await entry.getAttribute('data-value'), '98-发布成片');
    assert.equal(await page.getByRole('navigation', { name: '项目栏目', exact: true }).locator(':scope > button').last().getAttribute('aria-label'), '发布资料');
    assert.equal(await panel.getByRole('searchbox').count(), 0);
    assert.equal(await panel.locator(':scope > p.muted').count(), 0, '不显示目录说明');
    assert.equal(await panel.getByRole('link').count(), 0, '列表不再显示查看和下载');
    assert.equal(await panel.locator('.file-actions, .status-badge').count(), 0, '发布成片不显示确认状态');
    assert.equal(await panel.locator('.tree, details').count(), 0, '取消目录列表');
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第1集', '第2集', '第3集', '第4集', '第5集']);
    await page.getByRole('navigation', { name: '当前位置', exact: true }).getByText('发布成片（12）', { exact: true }).waitFor();
    const pagination = panel.locator('.pagination');
    assert.equal(await pagination.locator(':scope > nav').count(), 1, '文件名只显示在分页中间');
    assert.equal(await pagination.locator('.pagination-current').count(), 0, '不再显示页码和总计');
    assert.deepEqual(await pagination.locator(':scope > button').allTextContents(), ['上一页', '下一页']);
    const geometry = await pagination.evaluate(el => {
      const r = el.getBoundingClientRect(), nav = el.querySelector('nav').getBoundingClientRect();
      return { height: r.height, navTop: nav.top, tops: [...el.querySelectorAll('nav > button')].map(button => button.getBoundingClientRect().top), margin: getComputedStyle(el).marginTop };
    });
    assert.ok(geometry.height < 65, '分页栏收紧上下留白');
    assert.equal(geometry.margin, '0px');
    assert.ok(geometry.tops.every(top => Math.abs(top - geometry.navTop) < 1), '五个文件名始终在同一行');
    const spacing = await pagination.evaluate(el => ({ gap: getComputedStyle(el).columnGap, buttons: [...el.querySelectorAll(':scope > button')].map(button => ({ width: button.getBoundingClientRect().width, padding: getComputedStyle(button).paddingLeft })) }));
    assert.equal(spacing.gap, '12px');
    assert.ok(spacing.buttons.every(button => button.width >= 74 && button.padding === '14px'), '上一页下一页恢复正常宽度');
    assert.equal(await panel.getByRole('button', { name: '上一页', exact: true }).isDisabled(), true);
    const player = panel.locator('video');
    const downloadCurrent = async name => {
      const event = page.waitForEvent('download');
      await panel.getByRole('button', { name: '下载', exact: true }).click();
      const saved = await event;
      assert.equal(saved.suggestedFilename(), name);
      assert.deepEqual(await readFile(await saved.path()), sample);
    };
    assert.equal(await player.count(), 1);
    assert.equal(await player.evaluate(el => el.autoplay), false);
    await downloadCurrent(rootFile.name);
    await player.evaluate(async el => { el.muted = true; await el.play(); });
    await page.waitForFunction(() => document.querySelector('section.panel:not([hidden]) video').currentTime > 0);
    const previous = await player.elementHandle();
    await selector.getByRole('button', { name: '第3集', exact: true }).click();
    assert.equal(await previous.evaluate(el => el.isConnected), false, '切集卸载原视频');
    assert.equal(await player.getAttribute('aria-label'), '第3集.webm');
    assert.equal(await player.evaluate(el => el.paused), true);
    await downloadCurrent('第3集.webm');
    failDownload = true;
    await panel.getByRole('button', { name: '下载', exact: true }).click();
    const downloadFailure = page.locator('.floating-message').filter({ hasText: '示例下载失败' });
    await downloadFailure.waitFor();
    await downloadFailure.getByRole('button', { name: '关闭通知', exact: true }).click();
    failDownload = false;
    await downloadCurrent('第3集.webm');
    const notices = page.getByRole('button', { name: '关闭通知', exact: true });
    while (await notices.count()) await notices.first().click();
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第6集', '第7集', '第8集', '第9集', '第10集']);
    assert.equal(await player.getAttribute('aria-label'), '第6集.webm');
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.equal(await selector.getByRole('button').count(), 2);
    assert.equal(await player.getAttribute('aria-label'), '第11集.webm', '子目录视频纳入选集');
    assert.equal(await panel.getByRole('button', { name: '下一页', exact: true }).isDisabled(), true);
    await selector.getByRole('button').last().click();
    assert.equal(await player.getAttribute('aria-label'), longFile.name);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '长名称不得越界');
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-long-name.png`), animations: 'disabled' });
    await panel.getByRole('button', { name: '上一页', exact: true }).click();
    assert.equal(await player.getAttribute('aria-label'), '第6集.webm');
    await player.dispatchEvent('error');
    const mediaFailure = page.locator('.floating-message').filter({ hasText: '无法播放' });
    await mediaFailure.getByRole('button', { name: '重新加载视频', exact: true }).click();
    await mediaFailure.waitFor({ state: 'detached' });
    await player.evaluate(async el => { el.muted = true; await el.play(); });
    await page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('button', { name: '项目定位', exact: true }).click();
    assert.equal(await page.locator('.release-films-player').count(), 0, '离开栏目卸载播放器');
    await openRelease();
    assert.equal(await player.getAttribute('aria-label'), '第1集.webm', '重新进入栏目默认第一集');
    assert.equal(await player.evaluate(el => el.paused), true);
    await page.waitForFunction(() => document.querySelector('section.panel:not([hidden]) video')?.videoWidth > 0);
    const size = await player.evaluate(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height, ratio: el.videoWidth / el.videoHeight, limit: innerHeight * .65 }));
    assert.ok(Math.abs(size.width / size.height - size.ratio) < .01, '视频框与实际视频比例一致，无额外黑边');
    assert.ok(size.height <= size.limit + 1);
    const positions = await player.evaluate(el => { const video = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect(); return { center: video.left + video.width / 2, expected: parent.left + parent.width / 2 }; });
    assert.ok(Math.abs(positions.center - positions.expected) <= 1, '视频水平居中');
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-release-player.png`), animations: 'disabled' });
    mode = 'single'; await page.reload(); await openRelease();
    await page.getByRole('navigation', { name: '当前位置', exact: true }).getByText('发布成片（1）', { exact: true }).waitFor();
    const singleLayout = await panel.locator('.release-films-toolbar').evaluate(el => { const row = el.getBoundingClientRect(), pager = el.querySelector('.pagination').getBoundingClientRect(), download = el.querySelector('.release-films-download').getBoundingClientRect(); return { left: pager.left - row.left, width: pager.width, right: row.right - download.right }; });
    assert.ok(Math.abs(singleLayout.left) < 1 && singleLayout.width < 260, '单集整组分页靠左，保留按钮正常宽度和间距');
    assert.ok(Math.abs(singleLayout.right) < 1, '下载操作靠右');
    assert.equal(await panel.getByRole('button', { name: '上一页', exact: true }).isDisabled(), true);
    assert.equal(await panel.getByRole('button', { name: '下一页', exact: true }).isDisabled(), true);
    mode = 'empty'; await page.reload(); await openRelease();
    await panel.getByText('暂无发布成片视频。', { exact: true }).waitFor();
    assert.equal(await player.count(), 0);
    await page.getByRole('navigation', { name: '当前位置', exact: true }).getByText('发布成片（0）', { exact: true }).waitFor();
    assert.equal(await panel.getByRole('button', { name: '下载', exact: true }).isDisabled(), true);
    mode = 'error'; await page.reload(); await openRelease();
    const failure = page.locator('.floating-message').filter({ hasText: '资料读取失败' });
    await failure.getByRole('button', { name: '重新读取', exact: true }).waitFor();
    mode = 'files'; await failure.getByRole('button', { name: '重新读取', exact: true }).click();
    await selector.getByRole('button', { name: '第1集', exact: true }).waitFor();
    await failure.waitFor({ state: 'detached' });
    mode = 'priority'; await page.reload(); await openRelease();
    await selector.getByRole('button', { name: '片头', exact: true }).waitFor();
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['片头', '片尾', '第1集', '第2集', '第3集'], '全局排序后再分页，子目录片头和片尾优先');
    await page.getByRole('navigation', { name: '当前位置', exact: true }).getByText('发布成片（14）', { exact: true }).waitFor();
    assert.equal(await player.getAttribute('aria-label'), intro.name);
    await downloadCurrent(intro.name);
    await selector.getByRole('button', { name: '片尾', exact: true }).click();
    assert.equal(await player.getAttribute('aria-label'), outro.name);
    await downloadCurrent(outro.name);
    const priorityNotices = page.getByRole('button', { name: '关闭通知', exact: true });
    while (await priorityNotices.count()) await priorityNotices.first().click();
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-intro-outro.png`), animations: 'disabled' });
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第4集', '第5集', '第6集', '第7集', '第8集']);
    assert.equal(await player.getAttribute('aria-label'), '第4集.webm');
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    assert.deepEqual(await selector.getByRole('button').allTextContents(), ['第9集', '第10集', '第11集', longFile.name.replace(/\.[^.]+$/, '')], '其他视频保留原路径自然数字排序');
    await panel.getByRole('button', { name: '上一页', exact: true }).click();
    await panel.getByRole('button', { name: '上一页', exact: true }).click();
    assert.equal(await player.getAttribute('aria-label'), intro.name);
    navigation = 'full'; mode = 'files'; await page.reload();
    await entry.waitFor();
    const projectNav = page.getByRole('navigation', { name: '项目栏目', exact: true });
    const menu = page.getByRole('listbox', { name: '发布资料', exact: true });
    await entry.click();
    assert.deepEqual(await menu.locator('[role=option] > span:first-child').allTextContents(), ['封面资料', '账号资料', '发布成片'], '顺序不依赖后端目录排列');
    await entry.press('Escape');
    const related = projectNav.getByRole('combobox', { name: '相关资料', exact: true });
    await related.click();
    assert.deepEqual(await page.getByRole('listbox', { name: '相关资料', exact: true }).locator('[role=option] > span:first-child').allTextContents(), ['人物资料', '场景资料', '道具资料']);
    await related.press('Escape');
    assert.deepEqual(await projectNav.locator(':scope > button[role=combobox]').evaluateAll(elements => elements.map(el => el.getAttribute('aria-label'))), ['相关资料', '参考素材', '发布资料']);
    for (const [label, key] of [['封面资料', '10-封面资料'], ['账号资料', '11-社交媒体资料'], ['发布成片', '98-发布成片']]) {
      await entry.click();
      await menu.getByRole('option', { name: label, exact: true }).click();
      assert.equal(await entry.getAttribute('data-value'), key);
      await page.getByRole('navigation', { name: '当前位置', exact: true }).getByText(label === '发布成片' ? '发布成片（12）' : label, { exact: true }).waitFor();
    }
    await entry.focus(); await entry.press('ArrowDown'); await entry.press('Home'); await entry.press('Enter');
    assert.equal(await entry.getAttribute('data-value'), '10-封面资料', '键盘可返回封面资料');
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-release-group.png`), animations: 'disabled' });
    navigation = 'account'; await page.reload(); await entry.click();
    assert.deepEqual(await menu.locator('[role=option] > span:first-child').allTextContents(), ['账号资料'], '没有封面和成片时仍显示已有账号');
    await menu.getByRole('option', { name: '账号资料', exact: true }).click();
    assert.equal(await entry.getAttribute('data-value'), '11-社交媒体资料');
    navigation = 'none'; await page.reload(); await projectNav.waitFor();
    assert.equal(await entry.count(), 0, '没有发布相关目录时不显示空分组');
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []); assert.deepEqual(writes, []); assert.deepEqual(unexpected, []);
    console.log(`${viewport.width}px: left-packed pagination, right download/current filename+bytes/failure/retry/empty disabled, centered native-ratio player, selection and media/read retry; no errors/writes passed`);
    await context.close();
  }
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); await server.close(); }
