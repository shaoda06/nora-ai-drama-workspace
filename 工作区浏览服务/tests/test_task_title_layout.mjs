import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Exercise the real TaskSidebar and TaskCard; never submit or change a real task.
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
let server;
const base = process.env.TASK_CARD_BASE || await new Promise((resolve, reject) => {
  server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '0'], {
    cwd: fileURLToPath(new URL('../frontend', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  server.stdout.on('data', data => { output += data; const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0]; if (url) resolve(url); });
  server.stderr.on('data', data => { output += data; });
  server.once('error', reject);
  server.once('exit', code => reject(new Error(`Vite exited (${code}): ${output}`)));
});
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-task-title-'));
const nodeUrl = 'http://fixture.invalid:8188';
const task = { id: 'layout-fixture', project: '布局测试项目', title: 'EP002-C001-P001—P010 · 获批一采接续864×1536文戏＋去油二采',
  task_type: 'video-second-pass', prompt_id: 'fixture-prompt', status: 'running', connection: 'connected',
  node: null, remote_url: nodeUrl, progress: null, error: null, collected: 0, expected: 10,
  created_at: '2026-10-22T00:00:00Z', started_at: '2026-10-22T00:00:00Z', source_session_name: '' };
const snapshot = { tasks: [task], local_tasks: [], remote_nodes: [{ url: nodeUrl, name: '测试节点', connection: 'connected',
  queue: [{ prompt_id: task.prompt_id, status: 'running', queue_position: null }], running_count: 1, queued_count: 0,
  updated_at: '2026-10-22T00:00:00Z', error: null, queue_error: null }],
  local_counts: { [nodeUrl]: { queued: 0, paused: 0, history: 0 } }, history_updated_at: {} };
let browser;
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  for (const viewport of [{ width: 1362, height: 918 }, { width: 390, height: 844 }]) {
    task.status = 'running'; snapshot.remote_nodes[0].queue[0].status = 'running';
    const page = await browser.newPage({ viewport }), errors = [], writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/api/**', route => {
      if (route.request().method() !== 'GET') { writes.push(route.request().url()); return route.abort(); }
      const url = new URL(route.request().url());
      const data = url.pathname === '/api/projects' ? [] : url.pathname === '/api/service'
        ? { version: 'fixture', ready: false, environment: 'development' }
        : url.pathname === '/api/comfy/tasks' ? snapshot : undefined;
      assert.notEqual(data, undefined, 'unexpected API: ' + url.pathname);
      return route.fulfill({ json: data });
    });
    await page.clock.install({ time: new Date('2026-10-22T00:11:10Z') });
    await page.goto(base + '/#/');
    assert.ok(page.url().startsWith(base)); assert.ok(await page.title());
    await page.getByRole('button', { name: '展开任务进度', exact: true }).click();
    const card = page.locator('.comfy-task');
    await card.getByRole('heading', { name: task.title, exact: true }).waitFor();
    await page.evaluate(() => document.fonts.ready);
    const geometry = () => card.evaluate(element => {
      const rect = selector => element.querySelector(selector).getBoundingClientRect().toJSON();
      return { title: rect('h2'), copy: rect('.comfy-task-description'), timing: rect('.comfy-task-timing'),
        session: rect('.comfy-task-session'), details: rect('.comfy-task-details'),
        scrollWidth: document.documentElement.scrollWidth, font: getComputedStyle(element.querySelector('.comfy-task-timing')).fontVariantNumeric };
    });
    const first = await geometry();
    if (viewport.width > 700) {
      assert.equal(first.timing.width, 182, 'reserve a stable timing column');
      assert.ok(first.copy.x + first.copy.width + 11 <= first.timing.x);
    } else assert.ok(first.timing.y >= first.session.y + first.session.height, 'mobile timing sits below the description');
    assert.equal(first.font, 'tabular-nums');
    for (const milliseconds of [1000, 9000, 40000, 3600000]) {
      await page.clock.fastForward(milliseconds);
      const next = await geometry();
      for (const key of ['title', 'copy', 'timing', 'session', 'details']) assert.deepEqual(next[key], first[key], `layout moved after ${milliseconds}ms: ${key}`);
      assert.ok(next.scrollWidth <= viewport.width);
    }
    await card.getByText('来源会话：会话名称暂不可用', { exact: true }).waitFor();
    await card.getByText('任务详情', { exact: true }).click();
    assert.equal(await card.locator('details').getAttribute('open'), '');
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    await page.screenshot({ path: path.join(screenshots, `${viewport.width}-stable-title.png`) });
    task.status = 'queued'; snapshot.remote_nodes[0].queue[0].status = 'queued';
    await page.clock.fastForward(3000);
    await card.getByText('排队中', { exact: true }).waitFor();
    const waiting = await geometry();
    await page.clock.fastForward(1000);
    assert.deepEqual(await geometry(), waiting, 'waiting timer must also keep the same layout');
    await card.getByText(/提交时间：/).waitFor();
    assert.deepEqual(errors, []); assert.deepEqual(writes, []);
    console.log(`${viewport.width}px: fixed title/timing columns, running/waiting timers and seconds/minutes/hours stable, details interaction and no errors/writes passed`);
    await page.close();
  }
  console.log(`Screenshots: ${screenshots}`);
} finally { if (browser) await browser.close(); server?.kill(); }
