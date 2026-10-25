import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
function component(file, dependencies = {}) {
  const source = readFileSync(new URL(`../frontend/src/components/${file}.tsx`, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports,
    require: name => name.endsWith('.css') ? {} : dependencies[name] || require(name) });
  return module.exports;
}
const tooltip = component('PointerTooltip');
const titleStatusComponent = component('EpisodeTitleStatus', { './PointerTooltip': tooltip });
const { EpisodeButton } = component('EpisodeButton', { './PointerTooltip': tooltip, './EpisodeTitleStatus': titleStatusComponent });

test('working title has a visible marker independent of document approval', () => {
  const html = renderToStaticMarkup(React.createElement(EpisodeButton, {
    item: { kind: 'outline', name: 'EP001', title: '山间微光', titleStatus: '临时集名',
      statusHtml: '<span class="status-badge">已确认</span>' }, onSelect() {},
  }));
  assert.match(html, /class="episode-title-status status-orange">临时集名<\/span>/);
  assert.match(html, /class="status-badge">已确认<\/span>/);
  assert.match(html, /山间微光/);
});

test('explicit final naming is visible and unrecorded naming is not inferred', () => {
  for (const titleStatus of ['最终定名', '']) {
    const html = renderToStaticMarkup(React.createElement(EpisodeButton, {
      item: { kind: 'group', name: 'EP001', title: '山间微光', titleStatus,
        statusHtml: '<span class="status-badge">已完成</span>' }, onSelect() {},
    }));
    assert.equal(html.includes('episode-title-status'), !!titleStatus);
    assert.equal(html.includes('最终定名'), !!titleStatus);
    assert.equal(html.includes('episode-title-status status-green'), !!titleStatus);
    assert.match(html, /已完成/);
  }
});

test('pending episode naming remains independent of production status', () => {
  const html = renderToStaticMarkup(React.createElement(EpisodeButton, {
    item: { kind: 'group', name: 'EP002', title: '待定', titleStatus: '待定集名',
      statusHtml: '<span class="status-badge">进行中</span>' }, onSelect() {},
  }));
  assert.match(html, /class="episode-title-status status-gray">待定集名<\/span>/);
  assert.match(html, /class="status-badge">进行中<\/span>/);
});


test('breadcrumb title displays the shared naming badge without parentheses', () => {
  const { Breadcrumbs } = component('Breadcrumbs');
  const html = renderToStaticMarkup(React.createElement(Breadcrumbs, { items: [{ label: React.createElement(React.Fragment, null, 'EP002 · AI又不是许愿池 ', React.createElement(titleStatusComponent.EpisodeTitleStatus, { status: '最终定名' })) }] }));
  assert.match(html, /episode-title-status status-green/);
  assert.match(html, /AI又不是许愿池/);
  assert.doesNotMatch(html, /（最终定名）/);
});
