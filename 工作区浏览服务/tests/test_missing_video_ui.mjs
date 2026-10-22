// Response-only fixtures: never change real project files, tasks, or media.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_missing_video_ui.mjs URL PROJECT');
const out = path.join(os.tmpdir(), 'nora-missing-video-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1355, height: 925 } });
  const errors = [];
  const consoleErrors = [];
  const fixtureMediaErrors = [];
  const writes = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    // Empty fixture MP4/blob responses cannot satisfy Chrome's media range
    // request. Keep this expected media error separate from application errors.
    (message.text().endsWith('net::ERR_REQUEST_RANGE_NOT_SATISFIABLE') ? fixtureMediaErrors : consoleErrors).push(message.text());
  });
  if (process.env.FRONTEND_DIST) await page.route(base + '/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname !== '/' && !pathname.startsWith('/assets/')) return route.fallback();
    const file = path.join(process.env.FRONTEND_DIST, pathname === '/' ? 'index.html' : pathname);
    const contentType = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    return route.fulfill({ contentType, body: await readFile(file) });
  });
  await page.route('**/api/**', route => {
    if (route.request().method() === 'GET') return route.fallback();
    writes.push(route.request().url());
    return route.abort();
  });
  await page.route(/\.mp4(?:\?|$)/, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  const context = { scriptHtml: '<p>本轮分镜</p>', shots: [], prompts: { chinese: '本轮提示词' }, references: { common: [], segment: [] }, issues: [] };
  const video = (id, run, url = '', taskStatus = '', deliveryStatus = '') => ({ key: `EP001-C001-${id}-${run}-一采${url ? '.mp4' : ''}`,
    url, run, stage: '一采', approved: false, candidateNumber: Number(run.slice(1)), fileRevision: url ? 'fixture' : '', taskStatus, deliveryStatus, checkedAt: '', context });
  const segments = [
    { id: 'P001', videos: [video('P001', 'R003', '/fixture-old.mp4', '成功', '已取回'), video('P001', 'R004')] },
    { id: 'P002', videos: [video('P002', 'R001', '', '成功', '已取回，待人工审阅')] },
    { id: 'P003', videos: [video('P003', 'R001', '/fixture-current.mp4', '成功', '已取回')] },
    { id: 'P004', videos: [video('P004', 'R001', '', '排队中', '未取回')] },
  ].map(segment => ({ ...segment, duration: 3, scriptHtml: '本轮分镜' }));
  for (const video of [segments[0].videos[1], segments[1].videos[0]]) video.context = {
    ...context, scriptHtml: '', prompts: { english: '', chinese: '' }, issues: ['该次生成的资料关联尚未记录。'],
  };
  // The draft remains "prepared" while this candidate's actual task advances.
  const stateUrl = '/api/fixture-video-task';
  segments[3].videos[0].taskStateUrl = stateUrl;
  segments[3].videos[0].taskStatus = '已准备；实际执行见[后台共同状态及任务ID](../执行附件/private/后台任务状态.json)';
  let liveStatus = 'local_queued';
  let brokenStatus = false;
  await page.route('**/api/fixture-video-task', route => route.fulfill({ contentType: 'application/json',
    body: brokenStatus ? '{' : JSON.stringify({ id: 'fixture-task', status: liveStatus, updated_at: liveStatus }),
  }));
  await page.route('**/api/comfy/tasks/fixture-task/detail', route => route.fulfill({ json: {
    summary: { id: 'fixture-task', project, title: '候选任务详情', task_type: 'video-first-pass', status: 'failed',
      remote_url: 'https://example.invalid', enqueued_url: 'https://example.invalid',
      collected: 0, expected: 1, failure_stage: 'execution', error: '夹具中的详细失败原因' },
    events: [], outputs: [], records: [{ name: '完整过程记录', url: '/fixture-record' }],
    notification_batches: [], resolution_evidence: [], replacement_tasks: [],
  } }));
  await page.route('**/episodes/EP001', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.scenes = ['C001']; data.previousEpisode = null; data.productionIssues = []; data.warnings = [];
    data.segments = { C001: segments };
    data.sceneRounds = { C001: [{ number: 1, issues: [], script: null, storyboard: { kind: 'document', name: '分镜', version: 'v06' },
      segments: segments.map(segment => ({ id: segment.id, duration: 3, stage: '一采', run: segment.id === 'P001' ? 'R004' : 'R001', scriptHtml: '本轮分镜' })) }] };
    await route.fulfill({ response, json: data });
  });
  await page.goto(base + '/#/projects/' + encodeURIComponent(project), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP001' }).first().click();
  await page.getByRole('combobox', { name: '场次修改轮次', exact: true }).waitFor();
  const scene = page.locator('.episode-scene-content');
  const placeholder = page.locator('.segment-video .video-placeholder');
  const select = id => page.getByRole('button', { name: new RegExp('^分段 ' + id + '，') }).first().click();
  await select('P001');
  await page.screenshot({ path: path.join(out, 'not-generated.png') });
  assert.equal(await placeholder.innerText(), '尚未生成视频', 'planned revision mislabeled as lost media');
  assert.equal(await scene.getByText('部分分段暂无本轮视频。', { exact: true }).count(), 0);
  assert.equal(await scene.getByRole('region', { name: '场次提示' }).count(), 0, 'preparation alone must not create a shared message panel');
  assert.equal(await scene.getByText('P001的本轮一采 R004尚未生成视频', { exact: false }).count(), 0);
  assert.ok((await scene.locator('.scene-video-preparation').innerText()).includes('3段尚无可播放视频'));
  assert.ok(!(await scene.innerText()).includes('视频已不可播放'));
  assert.equal(await page.locator('.segment-video video').count(), 0, 'must not fall back to old R003');
  const script = page.locator('.segment-script-content');
  await script.getByRole('status').filter({ hasText: '现在看到的是第1轮保存的分镜（v06），不是生成视频时留下的记录。' }).waitFor();
  assert.equal(await script.locator('.generation-context-issues').count(), 0, 'unsubmitted plan labeled as a missing execution record');
  assert.ok((await script.innerText()).includes('本轮分镜'));
  assert.ok(!(await script.innerText()).includes('该次生成的资料关联尚未记录。'));
  await page.getByRole('button', { name: '提示词', exact: true }).click();
  await script.getByRole('status').filter({ hasText: '还没有实际生成时使用的提示词和素材记录。' }).waitFor();
  assert.ok(!(await script.innerText()).includes('现在看到的是第1轮保存的分镜'));
  assert.ok(!(await script.innerText()).includes('已缺失'));
  await page.getByRole('button', { name: '分镜脚本', exact: true }).click();
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).click();
  assert.equal(await page.getByRole('checkbox', { name: '连续播放', exact: true }).isChecked(), false);
  assert.equal(await scene.getByText('尚未生成视频', { exact: true }).count(), 1, 'continuous start duplicates player status');
  assert.ok(!(await scene.locator('[role=alert]').allTextContents()).some(text => text.includes('尚未生成')));
  await select('P002');
  assert.equal(await placeholder.innerText(), '已有视频不可播放，请检查视频文件及取回记录。');
  assert.equal(await script.locator('.generation-context-issues').count(), 1, 'real missing execution records must remain visible');
  assert.ok(!(await scene.innerText()).includes('尚未生成'));
  await page.screenshot({ path: path.join(out, 'unavailable.png') });
  await select('P004');
  await placeholder.getByRole('status').filter({ hasText: /^排队中$/ }).waitFor();
  for (const [status, message] of [
    ['queued', '任务已提交'], ['running', '正在生成中'], ['collecting', '正在取回视频'],
    ['completed', '生成已完成'], ['failed', '生成失败，请查看任务详情'],
    ['collection_failed', '视频取回失败，请查看任务详情'], ['paused', '任务已暂停'],
    ['cancelled', '任务已取消'],
  ]) {
    liveStatus = status;
    await placeholder.getByRole('status').filter({ hasText: new RegExp('^' + message + '$') }).waitFor({ timeout: 10000 });
    assert.ok(!(await placeholder.innerText()).includes('执行附件'));
    if (status === 'running') {
      await placeholder.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, 'running.png') });
      await page.setViewportSize({ width: 390, height: 844 });
      await placeholder.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, 'mobile-running.png') });
      await page.setViewportSize({ width: 1355, height: 925 });
    }
    assert.equal(await placeholder.getByRole('button', { name: '查看任务详情' }).count(), 1);
  }
  await placeholder.getByRole('button', { name: '查看任务详情' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('夹具中的详细失败原因', { exact: true }).waitFor();
  await dialog.getByText('技术记录', { exact: true }).click();
  await dialog.getByText('fixture-task', { exact: true }).waitFor();
  await dialog.getByRole('link', { name: '完整过程记录' }).waitFor();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  brokenStatus = true;
  await placeholder.getByRole('status').filter({ hasText: /^任务状态暂不可用$/ }).waitFor({ timeout: 10000 });
  brokenStatus = false;
  liveStatus = 'queued';
  await placeholder.getByRole('status').filter({ hasText: /^任务已提交$/ }).waitFor({ timeout: 10000 });
  assert.ok(!(await scene.innerText()).includes('已有视频不可播放'));
  await select('P003');
  await page.locator('.segment-video video').dispatchEvent('error');
  await page.getByRole('alert').filter({ hasText: '已有视频不可播放，请打开原文件检查。' }).waitFor();
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  await page.locator('.segment-video video').dispatchEvent('ended');
  assert.equal(await page.getByRole('button', { name: /^分段 P003，/ }).first().getAttribute('aria-pressed'), 'true');
  await scene.getByText('P004的本轮一采 R001等待提交', { exact: false }).waitFor();
  assert.ok(!(await scene.locator('[role=alert]').allTextContents()).some(text => text.includes('尚未生成')));
  await select('P001');
  await page.getByRole('combobox', { name: '版本切换', exact: true }).selectOption({ label: '候选三' });
  await page.getByText('该版本未登记整场轮次，不能连续播放；导出仍按第1轮。', { exact: true }).waitFor();
  assert.equal(await page.getByRole('checkbox', { name: '连续播放', exact: true }).isDisabled(), true);
  await select('P001');
  assert.equal(await scene.getByRole('region', { name: '场次提示' }).count(), 0, 'returning to the round clears the shared notice while progress stays separate');
  assert.equal(await scene.locator('.scene-video-preparation').count(), 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await placeholder.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'mobile-not-generated.png') });
  assert.deepEqual(errors, []);
  assert.deepEqual(consoleErrors, []);
  assert.deepEqual(writes, []);
  assert.ok((await page.title()).includes('Nora'));
  assert.ok(!(await page.locator('body').innerText()).includes('Internal Server Error'));
  console.log(JSON.stringify({ passed: true, checks: ['planned candidate', 'old candidate not substituted', 'queued candidate', 'missing retrieved video', 'player error', 'continuous start and next segment', 'desktop and mobile', 'live task transitions', 'read failure and recovery', 'details retain technical evidence'], url: page.url(), pageErrors: errors, consoleErrors, fixtureMediaErrors, productionWrites: writes.length, screenshots: out }));
} finally { await browser.close(); }
