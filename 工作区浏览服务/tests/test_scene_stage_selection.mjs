import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = require('react/jsx-runtime');

// Run the actual component's selection callbacks and arrival effect. Only hooks
// and child rendering are stubbed; no project files, requests, or media change.
function mount({ mixed = true, pending = false, registered = true } = {}) {
  const values = new Map();
  let effects = [];
  const video = (id, stage, run, url = '/fixture.mp4') => ({ key: `${id}-${run}-${stage}`, stage, run, url });
  const segments = [
    { id: 'P001', duration: 3, videos: [video('P001', '一采', 'R001')] },
    { id: 'P003', duration: 3, videos: [video('P003', '一采', 'R022'), video('P003', '二采', 'R009', pending ? '' : '/second.mp4')] },
  ];
  const scope = { project: 'fixture', episode: 'EP001', scene: 'C001' };
  const key = 'scene/fixture/EP001/C001';
  const round = { number: 1, issues: [], segments: segments.map(item => ({ id: item.id, duration: 3,
    stage: mixed && item.id === 'P003' ? '二采' : '一采', run: item.id === 'P001' ? 'R001' : mixed ? 'R009' : 'R022' })) };
  if (!registered) values.set(key + '/reviewRound', { stage: '二采', order: ['P003'],
    versions: { P003: { stage: '二采', run: 'R009', key: 'P003-R009-二采' } } });
  const react = {
    useEffect: callback => effects.push(callback),
    useState: initial => [initial, () => {}],
  };
  const children = { SegmentWorkspace() {}, SegmentStageStrip() {} };
  const dependencies = {
    react, 'react/jsx-runtime': jsx,
    '@tanstack/react-query': { useQuery: () => ({}), useQueryClient: () => ({}) },
    '../refreshPosition': { useRefreshState(stateKey, initial) {
      if (!values.has(stateKey)) values.set(stateKey, initial);
      return [values.get(stateKey), next => values.set(stateKey,
        typeof next === 'function' ? next(values.get(stateKey)) : next)];
    } },
    './RevisionNotes': { useRevisionNotesExport: () => ({}) },
    './useSceneVideoCache': { useSceneVideoCache: () => ({ total: 0, ready: 0, failures: [], sources: {} }) },
    './SegmentWorkspace': { SegmentWorkspace: children.SegmentWorkspace },
    './SegmentStageStrip': { SegmentStageStrip: children.SegmentStageStrip },
    '../previousEpisodeEnding': { PREVIOUS_ENDING: 'previous-ending' },
  };
  function load(name) {
    const source = readFileSync(new URL(`../frontend/src/components/${name}.tsx`, import.meta.url), 'utf8');
    const compiled = ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText;
    const exports = {};
    vm.runInNewContext(compiled, { exports, require: name => dependencies[name] || {} });
    return exports;
  }
  dependencies['./SegmentVideo'] = load('SegmentVideo');
  const { SceneWorkspace } = load('SceneWorkspace');
  const props = { scope, segments, sceneRounds: registered ? [round] : [], selectedRound: registered ? 1 : undefined,
    onRoundChange() {}, previousEnding: null, emptyMessage: '', revision: 1, directorFiles: [] };
  const find = (node, type) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === type) return node.props;
    for (const child of [node.props?.children].flat(Infinity)) {
      const result = find(child, type);
      if (result) return result;
    }
  };
  const render = () => {
    effects = [];
    const tree = SceneWorkspace(props);
    return { workspace: find(tree, children.SegmentWorkspace), navigation: find(tree, children.SegmentStageStrip) };
  };
  return { render, flush: () => effects.forEach(effect => effect()) };
}

test('mixed-stage arrivals use each segment stage before any click', () => {
  const app = mount();
  app.render(); app.flush();
  const initial = app.render();
  assert.equal(initial.workspace.selection.stage, '一采');
  assert.equal(initial.workspace.selection.key, 'P001-R001-一采');
});

test('clicking mixed-stage segments selects their exact stage and keeps candidates reachable', () => {
  const app = mount();
  app.render(); app.flush();
  app.render().navigation.onSelect('P003');
  let selected = app.render();
  assert.equal(selected.workspace.selection.stage, '二采');
  assert.equal(selected.workspace.selection.key, 'P003-R009-二采');
  selected.navigation.onSelect('P003');
  selected = app.render();
  assert.equal(selected.workspace.selection.stage, '二采', 'reselect must not write the mixed-stage label');
  assert.equal(selected.workspace.items.filter(item => item.stage === selected.workspace.selection.stage).length, 1);
  selected.navigation.onSelect('P001');
  assert.equal(app.render().workspace.selection.stage, '一采');
});

test('pending second pass retains its stage instead of falling back to playable first pass', () => {
  const app = mount({ pending: true });
  app.render().navigation.onSelect('P003');
  const { workspace } = app.render();
  assert.equal(workspace.selection.stage, '二采');
  assert.equal(workspace.selection.key, 'P003-R009-二采');
  assert.equal(workspace.items.find(item => item.key === workspace.selection.key).url, '');
});

test('single-stage registered rounds and legacy fixed playlists keep their stage', () => {
  for (const registered of [true, false]) {
    const app = mount({ mixed: false, registered });
    app.render().navigation.onSelect('P003');
    assert.equal(app.render().workspace.selection.stage, registered ? '一采' : '二采');
  }
});
