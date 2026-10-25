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
  const states = [];
  let hook = 0;
  let effects = [];
  const video = (id, stage, run, url = '/fixture.mp4') => ({ key: `${id}-${run}-${stage}`, stage, run, url, deliveryStatus: '' });
  const segments = [
    { id: 'P001', duration: 3, videos: [video('P001', '一采', 'R001')] },
    { id: 'P003', duration: 3, videos: [video('P003', '一采', 'R022'), video('P003', '二采', 'R009', pending ? '' : '/second.mp4')] },
  ];
  const scope = { project: 'fixture', episode: 'EP001', scene: 'C001' };
  const round = { number: 1, issues: [], segments: segments.map(item => ({ id: item.id, duration: 3,
    stage: mixed && item.id === 'P003' ? '二采' : '一采', run: item.id === 'P001' ? 'R001' : mixed ? 'R009' : 'R022' })) };
  const react = {
    useEffect: callback => effects.push(callback),
    useState: initial => {
      const index = hook++;
      if (!(index in states)) states[index] = initial;
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }];
    },
  };
  const children = { SegmentWorkspace() {}, SegmentStageStrip() {}, MessagePanel() {} };
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
    './MessagePanel': { MessagePanel: children.MessagePanel },
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
  const props = { view: 'segments', onViewChange(view) { props.view = view; }, scope, segments, sceneRounds: registered ? [round] : [], selectedRound: registered ? 1 : undefined,
    onRoundChange(number) { props.selectedRound = number; }, previousEnding: null, emptyMessage: '', revision: 1, directorFiles: [] };
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
    hook = 0;
    const tree = SceneWorkspace(props);
    return { workspace: find(tree, children.SegmentWorkspace), navigation: find(tree, children.SegmentStageStrip), messages: find(tree, children.MessagePanel) };
  };
  return { render, props, flush: () => effects.forEach(effect => effect()) };
}

test('mixed-stage arrivals use each segment stage before any click', () => {
  const app = mount();
  app.render(); app.flush();
  const initial = app.render();
  assert.equal(initial.workspace.selection.stage, '一采');
  assert.equal(initial.workspace.selection.key, 'P001-R001-一采');
  assert.equal('roundVersions' in initial.navigation, false, 'overall progress must not receive a round filter');
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

test('single-stage registered rounds and unregistered scenes keep candidates browsable', () => {
  for (const registered of [true, false]) {
    const app = mount({ mixed: false, registered });
    app.render().navigation.onSelect('P003');
    assert.equal(app.render().workspace.selection.stage, registered ? '一采' : '二采');
  }
});

test('an unregistered scene cannot create a temporary playlist or replace a manually chosen candidate', () => {
  const app = mount({ registered: false });
  app.render().navigation.onSelect('P003');
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  let state = app.render();
  assert.equal(continuousInput(state).disabled, true);
  continuousInput(state).onChange({ target: { checked: true } });
  state = app.render();
  assert.equal(continuousInput(state).checked, false);
  assert.equal(state.workspace.selection.key, 'P003-R022-一采');
  assert.match(state.messages.messages.find(message => message?.id === 'round-missing').content, /尚未登记整场轮次/);
});

function matchingRounds() {
  const app = mount();
  app.props.segments[0].videos.push({ key: 'P001-R002-一采', stage: '一采', run: 'R002', url: '/new.mp4' });
  app.props.segments[1].videos.push({ key: 'P003-R021-一采', stage: '一采', run: 'R021', url: '/orphan.mp4' });
  for (const number of [2, 3]) app.props.sceneRounds.push({ number, issues: [], segments: [
    { id: 'P001', duration: 5, stage: '一采', run: 'R002' },
    { id: 'P003', duration: 4, stage: '一采', run: 'R022' },
  ] });
  app.render().navigation.onSelect('P003');
  return app;
}

const continuousInput = state => state.workspace.continuousControl.props.children.find(child => child.type === 'input').props;

test('quality selection waits for a concrete version; selection chooses latest matching round and retains the segment', () => {
  const app = matchingRounds();
  app.render().workspace.onSelectionChange({ stage: '一采', key: '' });
  assert.equal(app.props.selectedRound, 1);
  assert.equal(continuousInput(app.render()).disabled, true);
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  assert.equal(app.props.selectedRound, 3);
  let state = app.render();
  assert.equal(state.workspace.segment, 'P003');
  assert.equal(state.workspace.selection.key, 'P003-R022-一采');
  assert.equal(state.messages.messages.some(message => message?.id === 'playback'), false, 'successful version-linked round change must not create a message');
  assert.equal(state.workspace.autoPlay, false);
  assert.equal(continuousInput(state).checked, false);
  state.navigation.onSelect('P001');
  assert.equal(app.render().workspace.selection.key, 'P001-R002-一采');
});

test('even a matching older round advances to the latest reuse; exact stage and run can select an earlier round', () => {
  const app = matchingRounds();
  app.props.selectedRound = 2;
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  assert.equal(app.props.selectedRound, 3);
  app.render().workspace.onSelectionChange({ stage: '二采', key: 'P003-R009-二采' });
  assert.equal(app.props.selectedRound, 1);
  assert.equal(app.render().workspace.segment, 'P003');
  assert.equal(app.render().workspace.selection.stage, '二采');
});

test('a concrete candidate remains selected when the matching round has another file with the same R', () => {
  const app = matchingRounds();
  app.props.segments[1].videos.unshift({ key: 'adopted/P003-R022-一采', stage: '一采', run: 'R022', url: '/adopted.mp4', approved: true });
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  assert.equal(app.props.selectedRound, 3);
  assert.equal(app.render().workspace.selection.key, 'P003-R022-一采');
  assert.equal(app.render().messages.messages.some(message => message?.id === 'playback'), false);
});

test('an unregistered version stays visible but cannot arm continuous playback or silently replace itself', () => {
  const app = matchingRounds();
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R021-一采' });
  let state = app.render();
  assert.equal(app.props.selectedRound, 1);
  assert.equal(state.workspace.selection.key, 'P003-R021-一采');
  assert.equal(continuousInput(state).disabled, true);
  assert.match(state.messages.messages.find(message => message?.id === 'review-round').content, /未登记整场轮次/);
  continuousInput(state).onChange({ target: { checked: true } });
  state = app.render();
  assert.equal(state.workspace.selection.key, 'P003-R021-一采');
  assert.equal(continuousInput(state).checked, false);
});

test('continuous playback preserves current selection, follows the chosen round, and does not loop', () => {
  const app = matchingRounds();
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  app.render().navigation.onSelect('P001');
  let state = app.render();
  continuousInput(state).onChange({ target: { checked: true } });
  state = app.render();
  assert.equal(state.workspace.selection.key, 'P001-R002-一采');
  assert.equal(state.workspace.autoPlay, false);
  assert.equal(continuousInput(state).checked, true);
  assert.equal(state.workspace.continuous, true, '连续播放状态传给播放器，关闭其循环');
  state.workspace.onVideoEnded();
  state = app.render();
  assert.equal(state.workspace.segment, 'P003');
  assert.equal(state.workspace.selection.key, 'P003-R022-一采');
  assert.equal(state.workspace.autoPlay, true);
  state.workspace.onVideoEnded();
  state = app.render();
  assert.equal(state.workspace.segment, 'P003');
  assert.equal(state.workspace.autoPlay, false);
  continuousInput(state).onChange({ target: { checked: false } });
  assert.equal(app.render().workspace.continuous, false);
});

test('continuous playback stops at missing next-round media rather than substituting an older video', () => {
  const app = matchingRounds();
  app.props.segments[1].videos.find(video => video.run === 'R022').url = '';
  app.render().workspace.onSelectionChange({ stage: '一采', key: 'P003-R022-一采' });
  assert.equal(app.props.selectedRound, 3, 'pending versions still match their registered round');
  app.render().navigation.onSelect('P001');
  continuousInput(app.render()).onChange({ target: { checked: true } });
  app.render().workspace.onVideoEnded();
  const state = app.render();
  assert.equal(state.workspace.segment, 'P001');
  assert.equal(state.workspace.autoPlay, false);
  assert.match(state.messages.messages.find(message => message?.id === 'playback').content, /不会换用其他版本/);
});
