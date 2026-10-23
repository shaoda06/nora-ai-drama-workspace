import { execFileSync } from 'node:child_process';

const git = args => execFileSync('git', args, { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
const prefix = '工作区浏览服务/frontend/src/';
const entries = git(['diff', '--cached', '--name-status', '-z', '--find-renames', '--diff-filter=ACMR']).split('\0');
const changed = [];
for (let i = 0; i < entries.length && entries[i];) {
  const status = entries[i++], oldPath = entries[i++];
  const path = /^[RC]/.test(status) ? entries[i++] : oldPath;
  if (path.startsWith(prefix) && /\.(css|tsx?|jsx?)$/.test(path)) changed.push({ status, path, oldPath });
}
if (!changed.length) {
  console.log('公共组件自动检查：无暂存前端源码变更；不涉及的依据仍写入W记录。');
} else {
  const { inspectSource, introducedIssues } = await import('./shared-component-rules.mjs');
  let errors = 0, reviews = 0;
  for (const { status, path, oldPath } of changed) {
    const previous = status === 'A' ? [] : inspectSource(oldPath.startsWith(prefix) ? oldPath.slice(prefix.length) : oldPath, git(['show', `HEAD:${oldPath}`]));
    const current = inspectSource(path.slice(prefix.length), git(['show', `:${path}`]));
    for (const issue of introducedIssues(previous, current)) {
      const blocking = issue.severity === 'error';
      if (blocking) errors++; else reviews++;
      console.log(`${blocking ? '阻止提交' : '人工核对'} ${path}:${issue.line} [${issue.rule}] ${issue.message}`);
    }
  }
  console.log(`公共组件自动检查：读取${changed.length}个暂存文件，${errors}项需修正，${reviews}项待人工判断。`);
  console.log('仍需人工核对动态样式、间接调用、业务差异及展示页同步，并在W记录写明范围与依据。');
  if (errors) process.exitCode = 1;
}
