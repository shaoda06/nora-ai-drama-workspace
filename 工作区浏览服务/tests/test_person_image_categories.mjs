import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const exports = {};
const dependencies = {
  react: React,
  'react/jsx-runtime': require('react/jsx-runtime'),
  './AssetMedia': { AssetMedia: ({ items }) => React.createElement('div', null, items.map(item =>
    React.createElement('span', { key: item.name }, item.name))) },
  './TabSelect': { TabSelect: () => null },
};
const source = readFileSync(new URL('../frontend/src/components/PersonImages.tsx', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { exports, require: name => dependencies[name] });
const { personImageCategory, PersonImages } = exports;

test('person foundation contains identity and body references, including historical names', () => {
  for (const type of ['人物上半身正面肖像', '人物上半身正面肖像图', '人物多视角参考图', '人物多视角参考图（人物本体六视图）']) {
    assert.equal(personImageCategory({ type, costume: '模板基础着装' }), '人物基础', type);
  }
  assert.equal(personImageCategory({}), '人物基础', 'the pending-candidate shortcut retains its empty fallback');
  assert.equal(personImageCategory({ type: '服装参考图', costume: '黑色皮衣坏小子' }), '服装');
});

test('dressed and supplementary character references do not fall into person foundation', () => {
  for (const type of ['角色多视角参考图', '单人全身造型参考图', 'Q版角色三视图', 'Q版全身试稿', '单张试装图']) {
    assert.equal(personImageCategory({ type, costume: '黑色皮衣坏小子' }), '穿衣造型', type);
  }
});

test('adopted, pending and historical outfit images share one category without changing source decisions', () => {
  const detail = {
    formal: [
      { type: '人物上半身正面肖像', name: '人物肖像', approved: true },
      { type: '服装参考图', name: '独立服装', approved: true },
      { type: '角色多视角参考图', name: '角色六视图', approved: true },
      { type: '单人全身造型参考图', name: '黑色皮衣坏小子v07', approved: true },
      { type: 'Q版角色三视图', name: 'Q版三视图v01', approved: true },
    ],
    candidates: [
      { type: 'Q版全身试稿', name: '待确认试稿', userDecision: '待确认' },
      { type: '单人全身造型参考图', name: '旧造型', userDecision: '已结束未采用' },
    ],
  };
  const before = JSON.stringify(detail);
  const html = renderToStaticMarkup(React.createElement(PersonImages, { detail, category: '穿衣造型', revision: 1 }));
  assert.match(html, /已采用图片（3张）/);
  assert.match(html, /黑色皮衣坏小子v07/);
  assert.match(html, /Q版三视图v01/);
  assert.match(html, /候选与审阅.*?（1张）/);
  assert.match(html, /历史版本.*?（1张）/);
  assert.doesNotMatch(html, /人物肖像|独立服装/);
  assert.equal(JSON.stringify(detail), before);
});
