import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync, copyFileSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { inspectSource, introducedIssues } from './shared-component-rules.mjs';
const here = dirname(fileURLToPath(import.meta.url));
const errors = (path, text) => inspectSource(path, text).filter(issue => issue.severity === 'error');

test('native UI and direct copy implementations are blocked outside their owners', () => {
  for (const text of ['<dialog />', '<select />', '<input type={"search"} />', '<button role="switch" />',
    '<button role="combobox" />', '<div role="dialog" />', '<a download href="/file" />',
    '<nav className="underline-tabs" />', '<div className="floating-message" />',
    'navigator.clipboard.writeText("text")', 'document.execCommand("copy")']) {
    assert.ok(errors('NewPage.tsx', text).length, text);
  }
  assert.equal(errors('components.tsx', '<dialog />').length, 0);
  assert.equal(errors('components/TabSelect.tsx', '<button role="combobox" />').length, 0);
  assert.equal(errors('components/CopyButton.tsx', 'navigator.clipboard.writeText("text")').length, 0);
  assert.equal(errors('Page.tsx', '<TabSelect items={[]} selected="" />').length, 0);
  assert.equal(errors('Page.tsx', 'const doc = "<dialog/>"; // navigator.clipboard.writeText("a")').length, 0);
});

test('layout allocation is allowed, while page-qualified component appearance is blocked', () => {
  assert.equal(errors('Page.css', '.panel .tab-select{width:100%;margin-top:10px;min-width:0}').length, 0);
  assert.equal(errors('Page.css', '.panel .tab-select{padding:1px;color:red}').length, 2);
  assert.equal(errors('style.css', '.panel .tab-select{padding:1px}').length, 1);
  assert.equal(errors('components/TabSelect.css', '.panel .tab-select{padding:1px}').length, 1);
  assert.equal(errors('components/TabSelect.css', '.tab-select.tab-select-compact{padding:1px}').length, 0);
  assert.equal(errors('Page.css', '/* .panel .tab-select{color:red} */ .panel{color:red}').length, 0);
  assert.equal(errors('Page.css', '[data-label=".tab-select"]{color:red}').length, 0);
  assert.equal(errors('Page.css', '.panel dialog{padding:0}').length, 1);
  assert.equal(errors('style.css', 'dialog.dialog-compact{padding:10px}').length, 0);
  assert.equal(errors('Page.css', '.header:has(.tabs-grouped){flex-wrap:wrap}').length, 0);
  assert.equal(errors('Page.css', '.header:has(:is(.tabs,.tab-select)){display:flex}').length, 0);
  assert.equal(errors('Page.css', '.header:has(.tabs) .tab-select{padding:1px}').length, 1);
  assert.equal(errors('Page.css', '.panel:has(dialog){display:flex}').length, 0);
  assert.equal(errors('Page.css', '.panel:has(.tabs) dialog{padding:1px}').length, 1);
  assert.equal(errors('Page.css', '.panel .tab-select:has(span){padding:1px}').length, 1);
});

test('object URLs require review rather than blocking valid media previews', () => {
  const issues = inspectSource('Page.tsx', 'URL.createObjectURL(file)');
  assert.equal(issues[0].severity, 'review');
  assert.equal(inspectSource('components/DownloadButton.tsx', 'URL.createObjectURL(file)').length, 0);
});

test('unchanged historical findings do not block; changes, added copies and media changes do', () => {
  assert.equal(introducedIssues(inspectSource('Page.tsx', '<dialog/>'), inspectSource('Page.tsx', '<><dialog/><dialog/></>')).length, 1);
  const before = inspectSource('Page.css', '.panel .tab-select{color:red}');
  assert.equal(introducedIssues(before, inspectSource('Page.css', '\n.panel .tab-select{color:red}\n.other{margin:0}')).length, 0);
  assert.equal(introducedIssues(before, inspectSource('Page.css', '.panel .tab-select{color:blue}')).length, 1);
  assert.equal(introducedIssues(before, inspectSource('Page.css', '.panel .tab-select{color:red}.panel .tab-select{color:red}')).length, 1);
  assert.equal(introducedIssues(before, inspectSource('Page.css', '@media(max-width:600px){.panel .tab-select{color:red}}')).length, 1);
});

test('real Git hook checks the index: rejects staged violations even when worktree is fixed', () => {
  const repo = mkdtempSync(join(tmpdir(), 'nora-shared-check-'));
  const frontend = join(repo, '工作区浏览服务/frontend'), source = '工作区浏览服务/frontend/src/Page.tsx';
  const run = (...args) => spawnSync('git', args, { cwd: repo, encoding: 'utf8', env: { ...process.env, GIT_CONFIG_GLOBAL: join(repo, 'no-global-config') } });
  const ok = (...args) => { const result = run(...args); assert.equal(result.status, 0, result.stderr); return result; };
  try {
    mkdirSync(join(frontend, 'src'), { recursive: true });
    ok('init', '-q'); ok('config', 'user.name', 'Shared UI Test'); ok('config', 'user.email', 'test@example.invalid');
    ok('config', 'commit.gpgsign', 'false');
    writeFileSync(join(repo, source), 'export const Page = () => <p>ok</p>;');
    ok('add', source); ok('commit', '-qm', 'fixture');
    mkdirSync(join(frontend, 'scripts'));
    for (const name of ['check-shared-components.mjs', 'shared-component-rules.mjs']) copyFileSync(join(here, name), join(frontend, 'scripts', name));
    symlinkSync(resolve(here, '../node_modules'), join(frontend, 'node_modules'), 'junction');
    // Hook wiring test only; the actual browser runner has its own fixture and negative tests.
    writeFileSync(join(frontend, 'scripts/check-shared-layout.mjs'), 'console.log("browser-check-invoked")');
    mkdirSync(join(repo, '.githooks'));
    copyFileSync(resolve(here, '../../../.githooks/pre-commit'), join(repo, '.githooks/pre-commit'));
    chmodSync(join(repo, '.githooks/pre-commit'), 0o755);
    ok('config', 'core.hooksPath', '.githooks');
    writeFileSync(join(repo, source), 'export const Page = () => <dialog />;'); ok('add', source);
    writeFileSync(join(repo, source), 'export const Page = () => <p>fixed only in worktree</p>;');
    const blocked = run('commit', '-qm', 'must reject');
    assert.notEqual(blocked.status, 0); assert.match(blocked.stdout + blocked.stderr, /阻止提交.*Page.tsx:1/);
    ok('add', source);
    writeFileSync(join(repo, source), 'export const Page = () => <dialog />;');
    writeFileSync(join(frontend, 'scripts/check-shared-layout.mjs'), 'console.error("browser-layout-failed"); process.exit(1)');
    const browserBlocked = run('commit', '-qm', 'must reject browser failure');
    assert.notEqual(browserBlocked.status, 0);
    assert.match(browserBlocked.stdout + browserBlocked.stderr, /browser-layout-failed/);
    writeFileSync(join(frontend, 'scripts/check-shared-layout.mjs'), 'console.log("browser-check-invoked")');
    const accepted = ok('commit', '-qm', 'clean index');
    assert.match(accepted.stdout + accepted.stderr, /0项需修正/);
    assert.match(accepted.stdout + accepted.stderr, /browser-check-invoked/);
    // Added files and deletions use the same hook; unrelated working changes stay ignored.
    const added = '工作区浏览服务/frontend/src/New.tsx';
    writeFileSync(join(repo, added), '<input type="search"/>'); ok('add', added);
    assert.notEqual(run('commit', '-qm', 'reject new').status, 0);
    ok('reset', '-q', '--', added);
    ok('restore', '--worktree', '--', source);
    const renamed = '工作区浏览服务/frontend/src/Renamed.tsx';
    ok('mv', source, renamed); ok('commit', '-qm', 'rename fixture');
    ok('rm', '-f', renamed); ok('commit', '-qm', 'delete fixture');
    writeFileSync(join(repo, 'README.md'), 'docs only'); ok('add', 'README.md');
    const docs = ok('commit', '-qm', 'docs');
    assert.doesNotMatch(docs.stdout + docs.stderr, /公共组件自动检查/);
  } finally { rmSync(repo, { recursive: true, force: true }); }
});
