// Real project UI, isolated Vite server and in-memory APIs. No production writes.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { createServer } = await import(require.resolve('vite'));
const react = (await import(require.resolve('@vitejs/plugin-react'))).default;
const sample = await readFile(new URL('../frontend/public/component-samples/video.webm', import.meta.url));
const screenshots = await mkdtemp(path.join(os.tmpdir(), 'nora-episode-notes-'));
const key = note => `round/${note.roundNumber}/${note.segment}/${note.stage}/${note.run}`;
const video = (scene, run, stage = '一采') => ({ key: `${scene}-${stage}-${run}`, run, stage, url: '/fixture/video.webm', candidateNumber: Number(run.slice(1)), approved: false,
  fileRevision: 'fixture', deliveryStatus: '已取回', taskStatus: '成功', checkedAt: '', context: { scriptHtml: '<p>测试分镜</p>', shots: scene === 'C001' && run === 'R002' ? [
    { id: `EP001-${scene}-SH001`, duration: 0.3, html: '<p>第一镜</p>' },
    { id: `EP001-${scene}-SH002`, duration: 0.6, html: '<p>第二镜</p>' },
    { id: `EP001-${scene}-SH003`, duration: 1.1, html: '<p>第三镜</p>' },
  ] : [], prompts: {}, references: { common: [], segment: [] }, issues: [] } });
const doc = title => ({ kind: 'document', name: title, key: title + '.md', version: 'v01', doc: { title, html: `<p>${title}</p>` } });
const round = (scene, number) => ({ number, episodeRound: true, created_at: '2026-10-26T00:00:00+08:00', script: doc('剧本'), storyboard: doc(scene), issues: [],
  segments: (scene === 'C001' ? [{ id: 'P001', duration: 2, stage: '一采', run: 'R002' }, { id: 'P002', duration: 2, stage: '二采', run: 'R004' }]
    : [{ id: 'P001', duration: 2, stage: '一采', run: number === 8 ? 'R002' : 'R003' }]).map(segment => ({ ...segment, scriptHtml: '<h4>SH001</h4><p><strong>起始画面：</strong>原始画面</p>', scriptUrl: '/fixture/board.md' })) });
let legacy = false, conflict = false, failRead = false, holdNextSegmentSave = null;
let saved, puts;
function reset() {
  const note = (segment, stage, run, text, roundNumber = 9) => ({ roundNumber, segment, stage, run, text, fileRevision: 'original-file', updatedAt: '2026-10-26T00:00:00+08:00' });
  const c1 = [note('P002', '二采', 'R004', '00.03.0秒，SH004：后面的镜头\n00.01.0秒，SH003：前面的镜头'), note('P001', '一采', 'R002', '00.00.0秒，SH001：C001第一段'), note('P001', '一采', 'R002', '旧轮意见不可带入', 8), note('P001', '一采', 'R001', '组合外版本不可带入')];
  const c2 = [note('P001', '一采', 'R003', '00.00.0秒，SH001：C002第一段')];
  saved = { episode: 'EP001', scenes: { C002: { notes: Object.fromEntries(c2.map(n => [key(n), n])), rounds: {} },
    C001: { notes: Object.fromEntries(c1.map(n => [key(n), n])), rounds: { 5: { number: 5, text: '旧整场意见', updatedAt: '' } } } }, rounds: {}, combinations: {} };
  puts = [];
}
const episode = () => ({ kind: 'group', name: 'EP001', title: '意见示例', children: [], materials: [], previousEpisode: null, warnings: [], productionIssues: [], script: doc('剧本'), scenes: ['C001', 'C002'],
  episodeRounds: legacy ? [] : [8, 9].map(number => ({ number, scenes: ['C001', 'C002'] })),
  sceneRounds: Object.fromEntries(['C001', 'C002'].map(scene => [scene, (legacy ? [scene === 'C001' ? 5 : 7] : [8, 9]).map(number => ({ ...round(scene, number), episodeRound: !legacy }))])),
  segments: { C001: [{ id: 'P001', duration: 2, videos: [video('C001', 'R001'), video('C001', 'R002')] }, { id: 'P002', duration: 2, videos: [video('C001', 'R004', '二采')] }],
    C002: [{ id: 'P001', duration: 2, videos: [video('C002', 'R002'), video('C002', 'R003')] }] } });
reset();
const unexpected = [];
const server = await createServer({ configFile: false, cacheDir: path.join(screenshots, 'vite-cache'), root: fileURLToPath(new URL('../frontend', import.meta.url)), define: { __APP_VERSION__: JSON.stringify('notes-fixture') }, server: { host: '127.0.0.1', port: 0 },
 plugins: [react(), { name: 'episode-notes-fixture', configureServer(vite) { vite.middlewares.use(async (req, res, next) => {
  const url = decodeURIComponent(new URL(req.url, 'http://fixture.invalid').pathname);
  if (url.startsWith('/fixture/')) { res.setHeader('Content-Type', 'video/webm'); return res.end(sample); }
  if (!url.startsWith('/api/')) return next();
  let data;
  if (url.includes('/revision-notes/')) {
    if (failRead) { res.statusCode = 503; data = { detail: '模拟读取失败' }; }
    else if (req.method === 'PUT') {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const value = JSON.parse(Buffer.concat(chunks).toString()); puts.push({ url, value });
      if (conflict) { res.statusCode = 409; data = { detail: '意见已在其他位置更新，请保留当前输入。' }; }
      else if (url.endsWith('/EP001/export')) {
        for (const note of value.notes) {
          assert.equal(saved.scenes[note.scene].notes[key(note)]?.text ?? '', note.expectedText);
          const { scene, expectedText, ...fields } = note;
          saved.scenes[scene].notes[key(note)] = { ...fields, updatedAt: '' };
        }
        for (const item of value.rounds) saved.rounds[item.number] = { number: item.number, text: item.text, updatedAt: '' };
        if (value.combination) {
          const item = value.combination;
          const id = Object.keys(item.scenes).sort().map(scene => `${scene}:${item.scenes[scene]}`).join('|');
          assert.equal(saved.combinations[id]?.text ?? '', item.expectedText);
          saved.combinations[id] = { scenes: item.scenes, text: item.text, updatedAt: '' };
        }
        data = saved;
      } else {
        const scene = url.split('/').at(-1);
        if ((saved.scenes[scene].notes[key(value)]?.text ?? '') !== value.expectedText) {
          res.statusCode = 409; data = { detail: '意见已在其他页面更新，请核对最新意见。' };
        } else {
          const { expectedText, ...fields } = value;
          const note = { ...fields, updatedAt: '' };
          saved.scenes[scene].notes[key(note)] = note; data = note;
          if (holdNextSegmentSave) { const pending = holdNextSegmentSave; holdNextSegmentSave = null; await pending; }
        }
      }
    } else { const scene = url.split('/').at(-1); data = scene === 'EP001' ? saved : saved.scenes[scene]; }
  } else if (req.method !== 'GET') { unexpected.push(`${req.method} ${url}`); res.statusCode = 405; data = {}; }
  else if (url === '/api/projects') data = [{ id: '意见示例', name: '意见示例' }];
  else if (url.endsWith('/status')) data = { revision: 1, updating: false, checking: false };
  else if (url.endsWith('/overview')) data = { active: [], warnings: [], directories: [{ name: '00-项目定位', label: '项目定位' }, { name: '09-剧集制作', label: '剧集制作' }] };
  else if (url.endsWith('/sections/00-项目定位')) data = { exists: false, groups: [] };
  else if (url.endsWith('/sections/09-剧集制作')) data = { kind: 'group', statistics: { total: 1, completed: 0, notStarted: 0, running: 1 }, children: [{ kind: 'group', name: 'EP001', title: '意见示例', key: 'EP001' }] };
  else if (url.endsWith('/episodes/EP001')) data = episode();
  else { unexpected.push(url); res.statusCode = 404; data = {}; }
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
 }); } }],
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
 for (const width of [1362, 390, 320]) {
  reset(); legacy = false; conflict = false; failRead = false;
  const context = await browser.newContext({ viewport: { width, height: 916 } });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(base + '/tests/project-switch.html#/projects/' + encodeURIComponent('意见示例'));
  await page.getByRole('button', { name: '剧集制作', exact: true }).click();
  await page.getByRole('button').filter({ hasText: 'EP001' }).first().click();
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  const scene = id => page.getByRole('button', { name: new RegExp('^场次 ' + id + ' ·') });
  assert.equal(await scene('C001').locator('.round-new-dot').count(), 0, '沿用视频的场次没有黄点');
  assert.equal(await scene('C002').locator('.round-new-dot').count(), 1, '本轮新视频所在场次显示黄点');
  assert.equal(await scene('C002').getAttribute('aria-description'), '本轮新生成视频');
  await page.screenshot({ path: path.join(screenshots, `scene-dots-${width}.png`) });
  const contentTab = name => page.locator('.segment-script [aria-label="分段文字内容"] button').filter({ hasText: new RegExp('^' + name + '$') });
  const pendingNote = 'C001切场前的待保存意见';
  const flushed = page.waitForResponse(response => response.url().endsWith('/revision-notes/EP001/C001') && response.request().method() === 'PUT');
  await page.getByRole('textbox', { name: '修改意见', exact: true }).fill(pendingNote);
  await scene('C002').click();
  await flushed;
  assert.equal(await page.locator('.segment-strip .round-new-dot').count(), 1, '场次与分段标记一致');
  assert.equal(await contentTab('修改意见').getAttribute('aria-current'), 'page', '手动切场保持修改意见');
  assert.equal(saved.scenes.C001.notes['round/9/P001/一采/R002'].text, pendingNote, '切场保存原场待保存输入');
  assert.equal(await page.getByRole('textbox', { name: '修改意见', exact: true }).inputValue(), '00.00.0秒，SH001：C002第一段', '不得把上场意见带到本场');
  await scene('C001').click();
  assert.equal(await page.getByRole('textbox', { name: '修改意见', exact: true }).inputValue(), pendingNote);
  await contentTab('提示词').click(); await scene('C002').click();
  assert.equal(await contentTab('提示词').getAttribute('aria-current'), 'page', '手动切场保持提示词');
  await contentTab('分镜脚本').click(); await scene('C001').click();
  assert.equal(await contentTab('分镜脚本').getAttribute('aria-current'), 'page', '手动切场保持分镜脚本');
  await contentTab('提示词').click();
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  await page.locator('.segment-video video').dispatchEvent('ended');
  await page.waitForFunction(() => document.querySelector('[aria-label="版本切换"]')?.getAttribute('data-value')?.endsWith('R004'));
  await page.locator('.segment-video video').dispatchEvent('ended');
  await page.locator('[aria-label="场次 C002 内容"]').waitFor();
  assert.equal(await contentTab('提示词').getAttribute('aria-current'), 'page', '连续播放跨场保持提示词');
  await scene('C001').click();
  await page.getByRole('button', { name: /^分段 P001，/ }).click();
  await contentTab('修改意见').click();
  await page.getByRole('checkbox', { name: '连续播放', exact: true }).check();
  const open = async () => { await page.getByRole('button', { name: '修改意见', exact: true }).click(); await page.getByRole('button', { name: '导出修改意见', exact: true }).click(); await page.locator('.revision-export-structured').waitFor(); };
  await open();
  const dialog = page.getByRole('dialog'), notes = dialog.locator('.revision-export-note');
  assert.equal(await notes.count(), 3);
  const titles = await notes.locator('strong').allTextContents();
  assert.match(titles[0], /C001.*P001.*一采.*R002.*候选二/);
  assert.match(titles[1], /C001.*P002.*二采.*R004.*候选四/);
  assert.match(titles[2], /C002.*P001.*一采.*R003.*候选三/);
  const summary = dialog.getByRole('textbox', { name: '第9轮 本轮汇总意见', exact: true });
  assert.equal(await summary.count(), 1);
  assert.equal(await dialog.getByText('旧整场意见', { exact: true }).count(), 0);
  await summary.fill('整集节奏自然，不要字幕');
  await page.locator('.segment-video video').dispatchEvent('ended');
  await page.waitForFunction(() => document.querySelector('[aria-label="版本切换"]')?.getAttribute('data-value')?.endsWith('R004'));
  await page.locator('.segment-video video').dispatchEvent('ended');
  await page.locator('[aria-label="场次 C002 内容"]').waitFor();
  assert.equal(await contentTab('修改意见').getAttribute('aria-current'), 'page', '连续播放跨场保持修改意见');
  assert.equal(await summary.inputValue(), '整集节奏自然，不要字幕', '跨场连播不能丢掉弹窗输入');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByText('已保存。', { exact: true }).waitFor();
  assert.equal(saved.rounds[9].text, '整集节奏自然，不要字幕');
  const copy = dialog.getByRole('button', { name: '复制', exact: true });
  await page.evaluate(() => { window.__copied = ''; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.__copied = text; } } }); });
  await copy.click(); const copied = await page.evaluate(() => window.__copied);
  assert.ok(copied.indexOf('C001 / 第9轮 / P001') < copied.indexOf('C001 / 第9轮 / P002'));
  assert.ok(copied.indexOf('SH003') < copied.indexOf('SH004'));
  assert.ok(copied.indexOf('SH004') < copied.indexOf('C002 / 第9轮 / P001'));
  assert.ok(!copied.includes('旧轮意见不可带入') && !copied.includes('组合外版本不可带入'));
  assert.ok(copied.includes('本轮汇总意见') && copied.includes('整集节奏自然，不要字幕'));
  await summary.fill('未保存的复制内容');
  await copy.click();
  assert.ok((await page.evaluate(() => window.__copied)).startsWith('【未保存草稿：'));
  assert.equal(saved.rounds[9].text, '整集节奏自然，不要字幕');
  conflict = true; await summary.fill('不能丢的输入');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByText(/未保存：.*其他位置更新/).waitFor();
  assert.equal(await summary.inputValue(), '不能丢的输入');
  await page.locator('.floating-message').filter({ hasText: '未保存：' }).getByRole('button', { name: '关闭通知', exact: true }).click();
  await dialog.getByRole('button', { name: '还原', exact: true }).click(); conflict = false;
  await page.screenshot({ path: path.join(screenshots, `${width}.png`) });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: /^场次 C002 ·/ }).click();
  await open(); assert.equal(await summary.inputValue(), '整集节奏自然，不要字幕');
  await dialog.getByRole('button', { name: '全部历史意见', exact: true }).click();
  assert.ok((await notes.allTextContents()).some(t => t.includes('第8轮')));
  assert.equal(await dialog.getByRole('textbox', { name: 'C001 第5轮 整场总体意见（历史只读）', exact: true }).inputValue(), '旧整场意见');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  const choose = page.getByRole('combobox', { name: '修改轮次', exact: true });
  await choose.click(); await page.getByRole('option', { name: /^第8轮/ }).click();
  assert.equal(await scene('C001').locator('.round-new-dot').count(), 1, '切换历史轮次后重新计算C001');
  assert.equal(await scene('C002').locator('.round-new-dot').count(), 1, '历史轮次首次生成的C002显示标记');
  await open(); assert.equal(await dialog.getByRole('textbox', { name: '第8轮 本轮汇总意见', exact: true }).inputValue(), '');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  // Real player time -> historical shot start -> cursor insertion -> in-memory autosave.
  await page.getByRole('button', { name: /^场次 C001 ·/ }).click();
  await page.getByRole('button', { name: /^分段 P001，/ }).click();
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  const editor = page.getByRole('textbox', { name: '修改意见', exact: true });
  const pass = page.getByRole('button', { name: 'SH003 本镜通过', exact: true });
  assert.equal(await page.getByRole('button', { name: /SH\d+ 本镜通过/ }).count(), 3);
  for (const cell of await page.locator('.shot-timeline-cell').all()) {
    const top = await cell.locator('.shot-timeline-item').boundingBox();
    const action = await cell.locator('.shot-timeline-pass').boundingBox();
    assert.ok(Math.abs(top.x + top.width / 2 - action.x - action.width / 2) < 1, '逐镜按钮与分镜格居中对齐');
    assert.ok(action.y >= top.y + top.height, '通过按钮位于进度条下方');
  }
  assert.deepEqual(await page.locator('.revision-note-label button').allTextContents(), ['插入时间', '清空']);
  const linkStyle = el => { const s=getComputedStyle(el); return Object.fromEntries(['fontSize','lineHeight','color','padding','borderRadius','textDecorationLine'].map(k=>[k,s[k]])); };
  assert.deepEqual(await pass.evaluate(linkStyle), await page.getByRole('button', {name:'插入时间',exact:true}).evaluate(linkStyle), '本镜通过与插入时间复用同一公共下划线链接规格');
  assert.match((await pass.evaluate(linkStyle)).textDecorationLine, /underline/);
  assert.equal(await page.locator('.revision-note-label label').count(), 0);
  await page.locator('.segment-video video').evaluate(video => video.play());
  await page.waitForFunction(() => document.querySelector('.segment-video video')?.currentTime >= 1.2);
  const playTenths = await page.locator('.segment-video video').evaluate(video => { video.pause(); return Math.floor(video.currentTime * 10); });
  await page.getByRole('button', { name: /^跳转到.*SH003，/ }).and(page.locator('[aria-current="step"]')).waitFor();
  await pass.click();
  const approved = '00.00.9秒，SH003：这个分镜没问题';
  await page.waitForFunction(text => document.querySelector('#revision-note-text')?.value.endsWith(text), approved);
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  assert.ok(saved.scenes.C001.notes['round/8/P001/一采/R002'].text.endsWith(approved));
  await page.getByRole('button', { name: '插入时间', exact: true }).click();
  assert.ok((await editor.inputValue()).endsWith(`00.01.${playTenths - 10}秒，SH003：`), '插入时间保留当前播放位置');
  await page.waitForFunction(() => { const input = document.querySelector('#revision-note-text'); return document.activeElement === input && input.selectionStart === input.value.length; });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  await editor.fill('前缀替换后缀');
  await page.waitForFunction(() => document.querySelector('#revision-note-text')?.value === '前缀替换后缀');
  await editor.evaluate(input => { input.focus(); input.setSelectionRange(2, 4); });
  await pass.click();
  assert.equal(await editor.inputValue(), '前缀\n' + approved + '后缀');
  await page.waitForFunction(position => document.querySelector('#revision-note-text')?.selectionStart === position, ('前缀\n' + approved).length);
  await page.locator('.segment-video video').evaluate(video => { video.currentTime = 0; video.dispatchEvent(new Event('timeupdate')); });
  await pass.focus(); await pass.press('Enter');
  assert.ok((await editor.inputValue()).endsWith(approved), '播放已回第一镜，第三镜按钮仍绑定第三镜起始时间');
  assert.equal(await page.locator('.segment-video video').evaluate(video => video.currentTime), 0, '通过操作不跳转或播放视频');
  const firstPass = page.getByRole('button', { name: 'SH001 本镜通过', exact: true });
  await firstPass.focus(); await firstPass.press('Enter');
  assert.ok((await editor.inputValue()).endsWith('00.00.0秒，SH001：这个分镜没问题'), '第一镜按钮使用首镜真实0秒');
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  await page.screenshot({ path: path.join(screenshots, `shot-pass-${width}.png`) });
  const box = await firstPass.boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= width, '刚操作的通过按钮在可视区内');
  const timelineBox = await page.locator('.shot-timeline-scroll').boundingBox();
  assert.ok(timelineBox.x >= 0 && timelineBox.x + timelineBox.width <= width, '窄屏分镜条内部滚动，不撑出视口');
  // A second page's save wins; editing/clearing a conflicted draft must not retry blindly.
  const noteId = 'round/8/P001/一采/R002';
  saved.scenes.C001.notes[noteId].text = '其他页面的新意见';
  await editor.fill('本页不能丢的草稿');
  await page.getByRole('button', { name: '核对最新意见', exact: true }).waitFor();
  assert.equal(await editor.inputValue(), '本页不能丢的草稿');
  assert.equal(saved.scenes.C001.notes[noteId].text, '其他页面的新意见');
  const countBeforeClear = puts.length;
  await page.getByRole('button', { name: '清空', exact: true }).click();
  await page.waitForTimeout(1200);
  assert.equal(puts.length, countBeforeClear, '冲突后清空不能自动覆盖其他页面');
  await page.getByRole('button', { name: '核对最新意见', exact: true }).click();
  const reconcile = page.getByRole('dialog', { name: '核对修改意见', exact: true });
  assert.equal(await reconcile.getByRole('textbox', { name: '项目中最新意见', exact: true }).inputValue(), '其他页面的新意见');
  await reconcile.getByRole('textbox', { name: '本页待保存意见', exact: true }).fill('核对后的合并意见');
  await page.screenshot({ path: path.join(screenshots, `conflict-${width}.png`) });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await reconcile.getByRole('button', { name: '保存核对后的本页意见', exact: true }).click();
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  assert.equal(saved.scenes.C001.notes[noteId].text, '核对后的合并意见');
  assert.equal(puts.at(-1).value.expectedText, '其他页面的新意见');
  let releaseSave;
  holdNextSegmentSave = new Promise(resolve => { releaseSave = resolve; });
  await editor.fill('请求中的第一版');
  await page.locator('.revision-note-state[data-state="saving"]').waitFor();
  await editor.fill('请求期间继续编辑的第二版');
  releaseSave();
  await page.locator('.revision-note-state[data-state="saved"]').waitFor();
  assert.equal(saved.scenes.C001.notes[noteId].text, '请求期间继续编辑的第二版');
  assert.equal(puts.at(-1).value.expectedText, '请求中的第一版');


  await page.getByRole('button', { name: /^场次 C002 ·/ }).click();
  await page.getByRole('button', { name: '修改意见', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: /SH\d+ 本镜通过/ }).count(), 0, '没有有效分镜条时不提供猜测起点的按钮');
  assert.equal(await page.getByRole('button', { name: '插入时间', exact: true }).isDisabled(), false);
  await choose.click(); await page.getByRole('option', { name: /^第9轮/ }).click();
  await page.getByRole('button', { name: '分镜修改', exact: true }).click();
  const story = page.getByRole('textbox', { name: /起始画面/ });
  await story.fill('修改后的起始画面');
  const countBeforeExport = puts.length;
  await page.getByRole('button', { name: '导出分镜', exact: true }).click();
  const storyExport = page.getByRole('textbox', { name: '导出分镜文本', exact: true });
  assert.ok((await storyExport.inputValue()).includes('依据：第9轮 · C002.md · v01'));
  assert.ok((await storyExport.inputValue()).includes('这是页签草稿，尚未写回项目分镜。'));
  assert.ok((await storyExport.inputValue()).includes('修改后的起始画面'));
  assert.equal(puts.length, countBeforeExport, '分镜编辑和导出不写服务端或发消息');
  const stored = await page.evaluate(() => JSON.parse(sessionStorage.getItem('nora-storyboard-draft/意见示例/EP001/C002')));
  assert.equal(stored.source, '第9轮 · C002.md · v01');
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '分段制作', exact: true }).click();
  await page.evaluate(values => sessionStorage.setItem('nora-storyboard-draft/意见示例/EP001/C002', JSON.stringify(values)), stored.values);
  await page.getByRole('button', { name: '分镜修改', exact: true }).click();
  assert.equal(await page.getByRole('textbox', { name: /起始画面/ }).innerText(), '修改后的起始画面');
  await page.getByRole('button', { name: '导出分镜', exact: true }).click();
  assert.ok((await storyExport.inputValue()).includes('依据：旧页签草稿，依据版本未记录'));

  await page.screenshot({ path: path.join(screenshots, `storyboard-handoff-${width}.png`) });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));

  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  await context.close(); console.log(`PASS ${width}px: 整集汇总排序、候选身份、统一总体意见、跨场恢复、旧历史及冲突保留输入`);
 }
 for (const width of [1362, 390, 320]) {
 legacy = true; reset();
 for (const [scene, value] of Object.entries(saved.scenes)) {
  value.notes = Object.fromEntries(Object.values(value.notes).map(note => {
   const value = note.roundNumber === 9 ? { ...note, roundNumber: scene === 'C001' ? 5 : 7 } : note;
   return [key(value), value];
  }));
 }
 const context = await browser.newContext({ viewport: { width, height: 916 } });
 const page = await context.newPage();
 await page.goto(base + '/tests/project-switch.html#/projects/' + encodeURIComponent('意见示例'));
 await page.getByRole('button', { name: '剧集制作', exact: true }).click();
 await page.getByRole('button').filter({ hasText: 'EP001' }).first().click();
 await page.getByRole('button', { name: '修改意见', exact: true }).click();
 await page.getByRole('button', { name: '导出修改意见', exact: true }).click();
 const dialog = page.getByRole('dialog');
 await dialog.getByRole('button', { name: '当前组合意见', exact: true }).waitFor();
 assert.equal(await dialog.locator('.revision-export-note').count(), 3);
 const legacyTitles = await dialog.locator('.revision-export-note strong').allTextContents();
 assert.ok(legacyTitles[0].includes('C001 / 第5轮') && legacyTitles[2].includes('C002 / 第7轮'));
 const summary = dialog.getByRole('textbox', { name: '本轮汇总意见', exact: true });
 assert.equal(await summary.count(), 1);
 assert.equal(await dialog.locator('.revision-export-note textarea:not([readonly])').count(), 0);
 await summary.fill('当前这一轮的整集汇总意见');
 await dialog.getByRole('button', { name: '关闭', exact: true }).click();
 await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
 assert.equal(await summary.inputValue(), '当前这一轮的整集汇总意见');
 await dialog.getByRole('button', { name: '保存', exact: true }).click();
 await page.getByText('已保存。', { exact: true }).waitFor();
 assert.equal(saved.combinations['C001:5|C002:7'].text, '当前这一轮的整集汇总意见');
 assert.deepEqual(saved.rounds, {}, '不能创建虚构的整集修改轮次');
 assert.equal(saved.scenes.C001.rounds[5].text, '旧整场意见');
 await page.screenshot({ path: path.join(screenshots, `legacy-${width}.png`) });
 await dialog.getByRole('button', { name: '关闭', exact: true }).click();
 await page.getByRole('button', { name: /^场次 C002 ·/ }).click();
 await page.getByRole('button', { name: '修改意见', exact: true }).click();
 await page.getByRole('button', { name: '导出修改意见', exact: true }).click();
 assert.equal(await summary.inputValue(), '当前这一轮的整集汇总意见');
 await page.evaluate(() => { window.__copied = ''; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.__copied = text; } } }); });
 await dialog.getByRole('button', { name: '复制', exact: true }).click();
 const copied = await page.evaluate(() => window.__copied);
 assert.ok(copied.includes('本轮汇总意见（C001第5轮、C002第7轮）') && copied.includes('当前这一轮的整集汇总意见'));
 await dialog.getByRole('button', { name: '关闭', exact: true }).click();
 failRead = true;
 await page.getByRole('button', { name: '导出修改意见', exact: true }).click();
 const message = page.locator('.floating-message').filter({ hasText: '导出资料读取失败' });
 await message.waitFor(); failRead = false;
 await message.getByRole('button', { name: '重试', exact: true }).click();
 await page.locator('.revision-export-structured').waitFor();
 assert.equal(puts.length, 1, '只保存一次整集组合汇总，失败重试不额外写入');
 await context.close();
 console.log(`PASS legacy ${width}px: 当前旧组合整集汇总保存、跨场恢复、复制、未保存提醒、原场意见保留与失败重试`);
 }
 console.log('截图：' + screenshots);
} finally { await browser.close(); await server.close(); }
