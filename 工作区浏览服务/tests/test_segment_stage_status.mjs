import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../frontend/src/components/SegmentStageStrip.tsx', import.meta.url), 'utf8');
const exports = {};
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { exports, require: () => ({}) });
const { segmentStageStatus } = exports;
const video = (stage, run, approved = false, extra = {}) => ({ stage, run, approved, ...extra });

test('all three adopted stages remain green, including an earlier adoption with a newer candidate', () => {
  const videos = [video('一采', 'R005', true), video('一采', 'R006', false, { taskStatus: '排队中' }),
    video('二采', 'R001', true), video('后处理', 'R001', true)];
  for (const stage of ['一采', '二采', '后处理']) {
    assert.equal(segmentStageStatus(videos, stage).symbol, '✓');
    assert.match(segmentStageStatus(videos, stage).detail, /已采纳/);
  }
  assert.match(segmentStageStatus(videos, '一采').detail, /R005/);
});

test('unapproved stage reports latest numeric revision and an absent stage remains unstarted', () => {
  const videos = [video('一采', 'R009', false, { url: '/candidate.mp4' }),
    video('一采', 'R010', false, { taskStatus: '排队中' })];
  const pending = segmentStageStatus(videos, '一采');
  assert.equal(pending.symbol, '−');
  assert.match(pending.detail, /R010 · 排队中/);
  assert.equal(segmentStageStatus(videos, '二采').symbol, '○');
});

test('a retrieved candidate or a failed task does not imply approval', () => {
  assert.equal(segmentStageStatus([video('二采', 'R001', false, { url: '/candidate.mp4' })], '二采').symbol, '−');
  const failed = segmentStageStatus([video('后处理', 'R002', false, { taskStatus: '失败' })], '后处理');
  assert.equal(failed.symbol, '−');
  assert.match(failed.detail, /失败/);
});
