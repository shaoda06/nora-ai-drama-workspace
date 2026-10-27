// Real history/detail components with in-memory API replies; no production API.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, writeFile, symlink, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { build, preview } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const frontend = fileURLToPath(new URL('../frontend/', import.meta.url));
const root = await realpath(await mkdtemp(join(tmpdir(), 'nora-closeout-ui-')));
let server, browser;
try {
  await symlink(join(frontend, 'node_modules'), join(root, 'node_modules'), 'junction');
  await writeFile(join(root, 'index.html'), '<html lang="zh"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/main.tsx"></script></body></html>');
  await writeFile(join(root, 'main.tsx'), `import React,{useState} from 'react';import{createRoot}from'react-dom/client';
    import{QueryClient,QueryClientProvider}from'@tanstack/react-query';
    import{TaskHistory}from${JSON.stringify(join(frontend, 'src/components/TaskHistory'))};
    import{TaskDetailDialog}from${JSON.stringify(join(frontend, 'src/components/TaskDetailDialog'))};
    import${JSON.stringify(join(frontend, 'src/style.css'))};
    function App(){const[id,setId]=useState(null);return <main><TaskHistory total={1} onDetails={setId}/>{id&&<TaskDetailDialog id={id} nodes={[]} close={()=>setId(null)}/>}</main>}
    createRoot(document.getElementById('root')).render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><App/></QueryClientProvider>);`);
  const config = { root, configFile: false, logLevel: 'error', plugins: [react()],
    define: { __APP_VERSION__: JSON.stringify('fixture') }, build: { outDir: 'dist' } };
  await build(config);
  server = await preview({ ...config, preview: { host: '127.0.0.1', port: 0 } });
  const base = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  for (const width of [1362, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 918 } });
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url());
      assert.equal(url.origin, base, 'no external traffic');
      assert.equal(req.method(), 'GET', 'read-only fixture');
      if (!url.pathname.startsWith('/api/')) return route.continue();
      requests.push(url.pathname + url.search);
      const summary = { id: 'fixture', project: '测试项目', title: '取回完成后的网页核验异常', task_type: 'video-first-pass',
        status: 'completed', category: 'history', remote_url: 'http://fixture.invalid', enqueued_url: 'http://fixture.invalid',
        created_at: '2026-10-27T01:00:00Z', notification: 'acknowledged', collected: 1, expected: 1,
        closeout: { status: 'browser_pending', error: '模拟资料解析冲突' } };
      if (url.pathname === '/api/comfy/history') return route.fulfill({ json: { items: [summary], total: 1, next_offset: null } });
      if (url.pathname === '/api/comfy/tasks/fixture/detail') return route.fulfill({ json: { summary, events: [], outputs: [], records: [], notification_batches: [], resolution_evidence: [], replacement_tasks: [] } });
      throw new Error('unexpected API: ' + url.pathname);
    });
    await page.goto(base);
    await page.getByText('成果已保存 · 网页待同步', { exact: true }).waitFor();
    await page.getByRole('combobox', { name: '历史任务结果' }).click();
    await page.getByRole('option', { name: '异常', exact: true }).click();
    await page.getByRole('button', { name: '查看取回完成后的网页核验异常详情' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByText('网页同步尚未完成', { exact: true }).waitFor();
    await dialog.getByText('模拟资料解析冲突', { exact: true }).waitFor();
    await dialog.getByText(/这不代表已经向用户交付/).waitFor();
    assert.ok(await dialog.evaluate(el => { const r = el.getBoundingClientRect(); return r.left >= -1 && r.right <= innerWidth + 1 && el.scrollWidth <= el.clientWidth + 1; }));
    assert.ok(requests.some(value => value.includes('result=abnormal')));
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`${width}px: closeout status, abnormal filter, recovery guidance and receipt meaning passed`);
  }
} finally { await browser?.close(); await server?.httpServer.close(); await rm(root, { recursive: true, force: true }); }
