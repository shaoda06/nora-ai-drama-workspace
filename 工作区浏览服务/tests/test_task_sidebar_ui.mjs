// Real TaskSidebar, synthetic tasks and in-memory writes. Never touches real queues.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const out = await mkdtemp(os.tmpdir() + '/nora-task-sidebar-');
const server = await createServer({ configFile: false, root: fileURLToPath(new URL('../frontend', import.meta.url)), plugins: [react()],
  server: { host: '127.0.0.1', port: 0 } });
await server.listen();
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
 for (const width of (process.argv.includes('--probe') ? [1362] : [1362,390,320])) {
  const page = await browser.newPage({ viewport: { width, height: 916 } }), errors = [], unexpected = [], writes = [];
  let rows = Array.from({ length: 20 }, (_, i) => ({ queue: 'local', id: 'fixture-' + (i + 1), project: '示例项目', title: '隔离任务 ' + (i + 1), task_type: 'video-first-pass', status: 'local_queued', category: 'queued',
    remote_url: 'http://fixture-node', created_at: '2026-10-27T00:00:00+08:00', source_session_name: '测试会话', can_transfer: true, transfer_targets: [{ url: 'http://fixture-backup', name: '备选节点' }] }));
  let failAction = false, failOrder = false, failReload = false, breakNextReload = false;
  let holdAction = false, releaseAction;
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('409') && !m.text().includes('503')) errors.push(m.text()); });
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    const body = req.method() !== 'GET' ? req.postDataJSON() : null;
    if (req.method() !== 'GET') writes.push({ path, body });
    if (path === '/api/comfy/tasks') {
      if (failReload) { failReload = false; return route.fulfill({ status: 503, json: { detail: '模拟刷新失败' } }); }
      const counts = node => ({ queued: rows.filter(t => t.remote_url === node && t.category === 'queued').length, paused: rows.filter(t => t.remote_url === node && t.category === 'paused').length, history: node === 'http://fixture-node' ? 1 : 0 });
      return route.fulfill({ json: { tasks: [], local_tasks: rows, remote_nodes: ['http://fixture-node','http://fixture-backup'].map((url,i) => ({ url, name: i ? '备选节点' : '默认节点', connection: 'connected', queue: [], running_count: 0, queued_count: 0, updated_at: '2026-10-27T00:00:00Z' })),
        local_counts: { 'http://fixture-node': counts('http://fixture-node'), 'http://fixture-backup': counts('http://fixture-backup') }, history_updated_at: {} } });
    }
    if (path === '/api/comfy/drag') return route.fulfill({ json: { token: 'fixture-lease' } });
    if (path === '/api/comfy/order') {
      if (failOrder) return route.fulfill({ status: 409, json: { detail: '模拟排序失败' } });
      rows = [...body.ids.map(id => rows.find(t => t.id === id)), ...rows.filter(t => !body.ids.includes(t.id))];
      return route.fulfill({ json: { ok: true } });
    }
    const match = path.match(/^\/api\/comfy\/tasks\/(fixture-\d+)\/(action|transfer)$/);
    if (match) {
      if (holdAction) { holdAction = false; await new Promise(resolve => { releaseAction = resolve; }); }
      if (failAction) { failAction = false; return route.fulfill({ status: 409, json: { detail: '模拟操作失败' } }); }
      const task = rows.find(t => t.id === match[1]);
      if (match[2] === 'transfer') task.remote_url = body.url;
      else if (body.action === 'pause') { task.status = 'paused'; task.category = 'paused'; }
      else if (body.action === 'resume') { task.status = 'local_queued'; task.category = 'queued'; }
      else if (body.action === 'insert') rows = [task, ...rows.filter(t => t !== task)];
      else if (body.action === 'cancel') rows = rows.filter(t => t !== task);
      if (breakNextReload) { failReload = true; breakNextReload = false; }
      return route.fulfill({ json: { local_task_id: task.id, status: task.status } });
    }
    if (path === '/api/comfy/history') return route.fulfill({ json: { items: [{ ...rows[0], category: 'history', status: 'completed', collected: 1, expected: 1 }], total: 1, next_offset: null } });
    if (path.endsWith('/detail')) return route.fulfill({ status: 503, json: { detail: '模拟详情读取失败' } });
    unexpected.push(path); return route.fulfill({ status: 404, json: {} });
  });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/task-sidebar.html`);
  assert.equal(await page.title(), '任务侧栏隔离回归');
  const toggle = page.getByRole('button', { name: '展开任务进度', exact: true });
  await toggle.click();
  const side = page.getByRole('complementary', { name: '生成任务进度' });
  const local = page.getByRole('region', { name: '本地队列' });
  const body = local.locator('.comfy-queue-body');
  const card = id => local.locator(`[data-local-task-id="fixture-${id}"]`);
  const dragRow = async (from, to) => {
    await card(from).waitFor();
    await page.waitForFunction(() => !document.querySelector('.local-queue-card button:disabled'));
    await body.evaluate((el,id) => { const card = el.querySelector(`[data-local-task-id="fixture-${id}"]`); el.scrollTop += card.getBoundingClientRect().top - el.getBoundingClientRect().top - 2; }, from);
    const before = await body.evaluate(el => el.scrollTop);
    const source = await card(from).locator('h2').boundingBox(), target = await card(to).locator('h2').boundingBox();
    const hit = await page.evaluate(({x,y}) => document.elementFromPoint(x,y)?.closest('[data-local-task-id]')?.getAttribute('data-local-task-id'), {x:source.x+10,y:source.y+8});
    assert.equal(hit,'fixture-'+from,JSON.stringify({width,from,source,target,body:await body.boundingBox(),scroll:before}));
    await page.mouse.move(source.x + 10, source.y + 8); await page.mouse.down();
    await page.locator('.local-queue-card-floating').waitFor();
    await page.mouse.move(target.x + 10, target.y + 8);
    await page.mouse.up();
    await page.locator('.local-queue-card-floating').waitFor({ state: 'detached' });
    await page.waitForFunction(() => !document.querySelector('.local-queue-card button:disabled'));
    return { before, after: await body.evaluate(el => el.scrollTop) };
  };
  const { before, after } = await dragRow(8,9);
  if (process.argv.includes('--probe')) {
    console.log(JSON.stringify({ before, after, order: rows.slice(5,10).map(t=>t.id) }));
    await page.getByRole('button', { name: '侧栏外部操作', exact: true }).click();
    console.log(JSON.stringify({ outsideClosed: await side.getAttribute('data-open') === 'false' }));
    await page.close(); continue;
  }
  assert.ok(before > 100 && Math.abs(before - after) <= 1, `拖拽前后滚动保持：${before} → ${after}`);
  await page.getByRole('status').filter({ hasText: '已更新队列顺序' }).waitFor();
  await page.getByRole('button', { name: '关闭通知', exact: true }).click();
  assert.ok(rows.findIndex(t => t.id === 'fixture-9') < rows.findIndex(t => t.id === 'fixture-8'), '真实拖拽改变保存顺序');
  const insert = card(8).getByRole('button', { name: '插队', exact: true });
  await insert.scrollIntoViewIfNeeded();
  const beforeInsert = await body.evaluate(el => el.scrollTop);
  await insert.click();
  await page.getByRole('status').filter({ hasText: '已移到队首' }).waitFor();
  const afterInsert = await body.evaluate(el => el.scrollTop);
  assert.ok(Math.abs(beforeInsert - afterInsert) <= 1, `插队保持点击时的滚动位置：${beforeInsert} → ${afterInsert}`);
  await card(11).getByRole('button', { name: '立即提交', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已接受立即提交请求' }).waitFor();
  await card(12).getByRole('button', { name: '暂停', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已暂停' }).waitFor();
  await local.getByRole('button', { name: /^暂停中/ }).click();
  await card(12).getByRole('button', { name: '恢复', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已恢复排队' }).waitFor();
  await local.getByRole('button', { name: /^排队中/ }).click();
  await card(13).getByRole('combobox', { name: '转移任务' }).click();
  await page.getByRole('option', { name: '备选节点', exact: true }).click();
  assert.equal(await side.getAttribute('data-open'),'true','侧栏菜单操作不触发外部关闭');
  await page.getByRole('status').filter({ hasText: '已转移到备选节点' }).waitFor();
  failAction = true;
  await card(14).getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '模拟操作失败' }).waitFor();
  assert.ok(rows.some(t=>t.id==='fixture-14'),'失败不伪造成功');
  await card(14).getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已取消' }).waitFor();
  breakNextReload = true;
  await card(15).getByRole('button', { name: '暂停', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: /操作已完成.*列表刷新失败/ }).waitFor();
  const closeMessage = page.getByRole('alert').filter({ hasText: '模拟操作失败' }).getByRole('button', { name: '关闭通知' });
  await closeMessage.click(); assert.equal(await side.getAttribute('data-open'),'true','通知操作不关闭侧栏');
  await page.getByRole('button', { name: '侧栏外部操作', exact: true }).click();
  assert.equal(await side.getAttribute('data-open'),'false');
  await toggle.click(); assert.equal(await side.getAttribute('data-open'),'true');
  const messages = page.getByRole('button', { name: '关闭通知', exact: true });
  while (await messages.count()) await messages.first().click();
  holdAction = true;
  await card(16).getByRole('button', { name: '暂停', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '正在处理任务操作' }).waitFor();
  await page.getByRole('button', { name: '侧栏外部操作', exact: true }).click();
  assert.equal(await side.getAttribute('data-open'),'false');
  releaseAction();
  await page.getByRole('status').filter({ hasText: /隔离任务 16.*已暂停/ }).waitFor();
  assert.equal(await side.getAttribute('data-open'),'false','关闭面板不取消操作，成功消息仍显示');
  await toggle.click();
  while (await messages.count()) await messages.first().click();
  const savedOrder = rows.map(task => task.id);
  failOrder = true;
  const failedDrag = await dragRow(17,18);
  await page.getByRole('alert').filter({ hasText: '模拟排序失败' }).waitFor();
  assert.deepEqual(rows.map(task => task.id),savedOrder,'排序失败保留后台原顺序');
  assert.equal(failedDrag.before,failedDrag.after,'失败回读也保持滚动');
  assert.ok(writes.at(-1).path==='/api/comfy/drag' && writes.at(-1).body.release===true,'失败也解除本次排序保护');
  assert.ok(await body.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'窄屏操作组正常换行，不横向撑宽队列');
  await local.getByRole('button', { name: /^历史/ }).click();
  await local.getByRole('button', { name: /查看.*详情/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  assert.equal(await side.getAttribute('data-open'),'true','详情弹窗操作不误关侧栏');
  assert.ok(await local.locator('.comfy-queue-body').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'窄屏队列按钮不横向撑宽');
  assert.equal(await page.locator('vite-error-overlay').count(),0);
  assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
  await page.screenshot({path:out+'/'+width+'.png'});
  console.log(JSON.stringify({width,passed:true,before,after,writes:writes.length,out}));
  await page.close();
 }
}finally{await browser.close();await server.close();}
