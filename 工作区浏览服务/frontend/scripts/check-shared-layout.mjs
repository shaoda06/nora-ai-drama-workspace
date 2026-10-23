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
    await checkSharedNavigation(page, width, selfTest);
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
