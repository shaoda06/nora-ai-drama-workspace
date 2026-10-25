// Real project route, switcher and page. All project responses are local read-only fixtures.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-project-switch-'));
const projects = ['甲项目', '乙项目'];
const sections = ['00-项目定位', '01-主旨与简介'];
const requests = [], unexpected = [];
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)),
  define: { __APP_VERSION__: JSON.stringify('switch-fixture') }, server: { host: '127.0.0.1', port: 0 },
  plugins: [react(), { name: 'project-switch-fixture', configureServer(vite) {
    vite.middlewares.use((req, res, next) => {
      const url = decodeURIComponent(new URL(req.url, 'http://fixture.invalid').pathname);
      if (!url.startsWith('/api/')) return next();
      requests.push(`${req.method} ${url}`);
      assert.equal(req.method, 'GET');
      let data;
      if (url === '/api/projects') data = projects.map(id => ({ id, name: id }));
      else {
        const match = url.match(/^\/api\/projects\/([^/]+)\/(.+)$/);
        const [, name, route] = match || [];
        if (projects.includes(name) && route === 'status') data = { revision: 1, checking: false, updating: false };
        else if (projects.includes(name) && route === 'overview') data = { active: [], warnings: [], directories: sections.map(name => ({ name, label: name.slice(3) })) };
        else if (projects.includes(name) && sections.includes(route?.replace('sections/', ''))) data = { exists: true, html: `<p>${name}的${route.slice(12)}正文</p>`, groups: [] };
        else { unexpected.push(url); res.statusCode = 404; data = {}; }
      }
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
    });
  } }],
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  for (const width of [1362, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 916 } });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    const url = `${base}/tests/project-switch.html#/projects/${encodeURIComponent(projects[0])}`;
    await page.addInitScript(({ href, project }) => {
      sessionStorage.setItem('nora-auto-refresh-position', JSON.stringify({ href, scrollY: 0, values: { [`project/${project}/section`]: '01-主旨与简介' } }));
    }, { href: url, project: projects[0] });
    await page.goto(url);
    const body = page.locator('section.panel:not([hidden]) .prose');
    await body.getByText('甲项目的主旨与简介正文', { exact: true }).waitFor();
    const switchProject = async name => {
      await page.getByRole('combobox', { name: '切换项目', exact: true }).click();
      await page.getByRole('option', { name: new RegExp(`^0[12]-${name}`) }).click();
    };
    await switchProject('乙项目');
    try { await body.getByText('乙项目的项目定位正文', { exact: true }).waitFor({ timeout: 4000 }); }
    catch (error) {
      console.error(JSON.stringify({ width, heading: await page.locator('nav.breadcrumbs').innerText(), panels: await page.locator('section.panel').count(), requests }, null, 2));
      throw error;
    }
    await page.getByRole('navigation', { name: '项目栏目', exact: true }).getByRole('button', { name: '主旨与简介', exact: true }).click();
    await body.getByText('乙项目的主旨与简介正文', { exact: true }).waitFor();
    await switchProject('甲项目');
    await body.getByText('甲项目的项目定位正文', { exact: true }).waitFor();
    await switchProject('乙项目');
    await body.getByText('乙项目的项目定位正文', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(screenshots, `${width}.png`), fullPage: true });
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    await context.close();
  }
  console.log(`PASS: 项目恢复后下拉切换、栏目切换、往返切换；1362/390/320px；无写请求或浏览器错误。截图：${screenshots}`);
} finally { await browser.close(); await server.close(); }
