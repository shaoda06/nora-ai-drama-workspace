// Browser-only fixtures: no project or task writes, no generated video decoding.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base, project] = process.argv.slice(2);
assert.ok(base && project, 'Usage: node tests/test_scene_rounds_ui.mjs URL PROJECT');
const out = path.join(os.tmpdir(), 'nora-scene-rounds-ui');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  let refreshRevision = 0;
  const statusPath = '/api/projects/' + encodeURIComponent(project) + '/status';
  const status = await (await fetch(base + statusPath)).json();
  await page.route('**/status', route => new URL(route.request().url()).pathname === statusPath
    ? route.fulfill({ json: { ...status, revision: status.revision + refreshRevision, updating: false, checking: false } }) : route.continue());
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/api/**', route => route.request().method() === 'GET' ? route.fallback() : route.abort());
  await page.route(/\.mp4(?:\?|$)/, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  const video = (id, run, stage = '一采', pending = false) => ({ key: `EP003-C001-${id}-${run}-${stage}`, url: pending ? '' : `/fixture-${id}-${run}.mp4`,
    run, stage, approved: false, candidateNumber: Number(run.slice(1)), fileRevision: '', deliveryStatus: pending ? '未取回' : '已取回', taskStatus: pending ? '排队中' : '成功', checkedAt: '',
    context: { scriptHtml: `<p>${id}-${run}对应分镜</p>`, shots: [], prompts: { chinese: `${id}-${run}中文方案`, english: `${id}-${run} submitted prompt` }, references: { common: [], segment: [] }, issues: [] } });
  const segments = ['P001', 'P002', 'P003'].map(id => ({ id, duration: 3, historical: id === 'P003', scriptHtml: '',
    videos: [video(id, 'R001'), ...(id === 'P001' ? [video(id, 'R002', '一采', true), video(id, 'R001', '二采')] : [])] }));
  const document = (kind, version) => ({ kind: 'document', name: `${kind}-${version}`, key: `fixture/${kind}-${version}.md`, version,
    doc: { title: `${kind}-${version}`, html: `<h1>${kind}-${version}轮次原文</h1><p>对应资料</p>`, meta: { 文档版本: version } } });
  const round = (number, ids) => ({ number, created_at: '2026-10-17T20:00:00+08:00', note: '测试组合', issues: [],
    script: document('剧本', number === 1 ? 'v1' : 'v2'), storyboard: document('分镜', number === 1 ? 'v1' : 'v2'),
    segments: ids.map(id => ({ id, duration: 3, stage: '一采', run: number === 2 && id === 'P001' ? 'R002' : 'R001', scriptHtml: `${id}轮次分镜` })) });
  const fixtureRounds = [round(1, ['P003', 'P001', 'P002']), round(2, ['P001', 'P002'])];
  await page.route('**/episodes/EP003', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.scenes = ['C001']; data.previousEpisode = null; data.productionIssues = []; data.warnings = [];
    data.segments = { C001: segments }; data.sceneRounds = { C001: fixtureRounds };
    await route.fulfill({ response, json: data });
  });
  await page.route('**/revision-notes/**', route => route.fulfill({ json: { notes: {
    old: { segment: 'P001', run: 'R001', stage: '一采', text: '旧轮意见', updatedAt: '2026-10-17T20:00:00+08:00', fileRevision: '' },
    current: { segment: 'P001', run: 'R002', stage: '一采', text: '新轮意见', updatedAt: '2026-10-17T20:00:00+08:00', fileRevision: '' }
  } } }));
  await page.goto(base + '/#/projects/' + encodeURIComponent(project), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP003' }).first().click();
  const choose = page.getByRole('combobox', { name: '场次修改轮次', exact: true });
  await choose.waitFor();
  assert.equal(await choose.inputValue(), '2');
  const stage = page.getByRole('combobox', { name: '画质选择' });
  const version = page.getByRole('combobox', { name: '版本切换' });
  assert.equal(await stage.inputValue(), '一采');
  assert.ok((await version.inputValue()).includes('R002'));
  assert.equal(await page.locator('.segment-video video').count(), 0, 'pending round used old video');
  assert.ok((await page.locator('.scene-video-preparation').innerText()).includes('1段尚无可播放视频'));
  await page.getByRole('button', { name: '提示词', exact: true }).click();
  assert.ok((await page.locator('.segment-script-content').innerText()).includes('P001-R002中文方案'));
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).click();
  assert.equal(await page.getByRole('checkbox', { name: '连续播放', exact: true }).isChecked(), false);
  assert.ok((await page.locator('.scene-workspace-tabs').locator('..').innerText()).includes('不可播放'));
  assert.ok((await version.inputValue()).includes('R002'));
  await choose.selectOption('1');
  assert.ok((await page.getByRole('group', { name: '本场分段', exact: true }).getByRole('button').first().getAttribute('aria-label')).includes('P003'));
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  await page.locator('.segment-video video').dispatchEvent('ended');
  assert.equal(await page.getByRole('button', { name: /^分段 P001，/ }).first().getAttribute('aria-pressed'), 'true');
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).uncheck();
  await page.getByRole('button', { name: /^分段 P001，/ }).first().click();
  assert.ok((await version.inputValue()).includes('R001-一采'));
  await page.getByRole('button', { name: '本段最新版本', exact: true }).click();
  assert.equal(await stage.inputValue(), '一采', 'latest jumped to old second-pass');
  assert.ok((await version.inputValue()).includes('R002-一采'));
  assert.ok(await page.getByText('当前查看版本不属于本轮，导出仍按本轮版本。', { exact: true }).isVisible());
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  await page.getByRole('button', { name: '导出修改意见', exact: true }).click();
  const exported = page.getByRole('textbox', { name: '导出修改意见文本', exact: true });
  await exported.waitFor();
  assert.ok((await exported.inputValue()).includes('第1轮审看意见'));
  assert.ok((await exported.inputValue()).includes('旧轮意见'));
  assert.ok(!(await exported.inputValue()).includes('新轮意见'));
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '场次分镜', exact: true }).click();
  assert.ok(await page.getByText('分镜-v1轮次原文', { exact: true }).isVisible());
  await page.getByRole('button', { name: '查看本集剧本', exact: true }).click();
  assert.ok(await page.getByText('剧本-v1轮次原文', { exact: true }).isVisible());
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '最新修改轮次', exact: true }).click();
  assert.equal(await choose.inputValue(), '2');
  assert.ok(await page.getByText('分镜-v2轮次原文', { exact: true }).isVisible());
  await page.getByRole('button', { name: '分段制作', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: /^分段 P003，/ }).count(), 0);
  await page.getByRole('button', { name: /^分段 P002，/ }).first().click();
  assert.ok((await version.inputValue()).includes('R001'), 'unchanged segment was renumbered');
  fixtureRounds.push(round(3, ['P001', 'P002']));
  refreshRevision = 1;
  await page.waitForFunction(() => document.querySelector('select[aria-label="场次修改轮次"]')?.options.length === 3);
  assert.equal(await choose.inputValue(), '2', 'new arrival replaced currently viewed round');
  await page.getByRole('button', { name: '最新修改轮次', exact: true }).click();
  assert.equal(await choose.inputValue(), '3');
  await page.locator('.scene-round-selector').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'desktop-round-selection.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.scene-round-selector').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'mobile-round-selection.png') });
  assert.deepEqual(errors, []);
  const evidence = { url: page.url(), title: await page.title(), checks: ['round defaults', 'pending revision retained', 'stage-scoped latest', 'outside-round notice', 'round-scoped note export', 'script and storyboard versions', 'historical segment order', 'unchanged run inheritance', 'fixed-round continuous playback', 'missing clip stops playback', 'new round does not replace current selection'], pageErrors: errors, productionWrites: 0 };
  await writeFile(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
} finally { await browser.close(); }
