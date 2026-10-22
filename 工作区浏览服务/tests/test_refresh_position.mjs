import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(process.env.NORA_REFRESH_SOURCE || new URL('../frontend/src/refreshPosition.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

// Exercise the real hook's setter against React's Object.is state bailout.
// No browser storage, project files, or production requests are modified.
function mount(storage = new Map(), href = 'http://localhost/#/projects/fixture') {
  let entry;
  let updates = 0;
  const exports = {};
  const events = new Map();
  const react = {
    useState(initial) {
      entry ??= initial();
      return [entry, next => {
        const value = typeof next === 'function' ? next(entry) : next;
        if (!Object.is(entry, value)) { entry = value; updates++; }
      }];
    },
    useCallback: callback => callback,
    useEffect: effect => { effect(); },
  };
  vm.runInNewContext(compiled, {
    exports, require: name => { assert.equal(name, 'react'); return react; },
    sessionStorage: { getItem: key => storage.get(key) || null, removeItem: key => storage.delete(key), setItem: (key, value) => storage.set(key, value) },
    window: { location: { href }, scrollY: 640, addEventListener: (event, callback) => events.set(event, callback) },
  });
  return { render: (key, initial) => exports.useRefreshState(key, initial), updates: () => updates,
    pagehide: () => events.get('pagehide')?.(), save: exports.saveRefreshPosition };
}

test('unchanged candidate selection settles instead of continuously scheduling renders', () => {
  const hook = mount();
  const chosen = { P001: { stage: '一采', key: 'R002' } };
  for (let render = 0; render < 10; render++) {
    const [, setSelection] = hook.render('selections', chosen);
    // SceneWorkspace returns the previous selection when no candidates arrive.
    setSelection(previous => previous);
  }
  assert.equal(hook.updates(), 0);
});

test('setting the same primitive value is a no-op', () => {
  const hook = mount();
  const [, setView] = hook.render('view', 'segments');
  setView('segments');
  assert.equal(hook.updates(), 0);
});

test('real candidate changes and functional updates still apply', () => {
  const hook = mount();
  const [, setCount] = hook.render('count', 1);
  setCount(previous => previous + 1);
  assert.equal(hook.render('count', 1)[0], 2);
  assert.equal(hook.updates(), 1);
});

test('changing a position key still resets to its own initial value', () => {
  const hook = mount();
  const [, setView] = hook.render('first/view', 'segments');
  setView('storyboard');
  hook.render('second/view', 'segments');
  assert.equal(hook.render('second/view', 'segments')[0], 'segments');
});

test('ordinary reload saves and restores the current project page and scroll position', () => {
  const storage = new Map();
  const page = mount(storage);
  const [, setSection] = page.render('project/fixture/section', '00-项目定位');
  setSection('09-剧集制作');
  page.render('project/fixture/section', '00-项目定位');
  page.pagehide();
  const snapshot = JSON.parse(storage.get('nora-auto-refresh-position'));
  assert.equal(snapshot.scrollY, 640);
  const reloaded = mount(storage);
  assert.equal(reloaded.render('project/fixture/section', '00-项目定位')[0], '09-剧集制作');
  assert.equal(storage.has('nora-auto-refresh-position'), false, 'restore snapshot is consumed once');
});

test('ordinary reload preserves nested review choices', () => {
  for (const [key, initial, selected] of [
    ['episode', null, 'EP002'], ['scene', '', 'C001'], ['segment', 'P001', 'P005'],
    ['round', 1, 17], ['version', 'R001', 'R010'], ['tab', 'script', 'prompt'],
  ]) {
    const storage = new Map();
    const page = mount(storage);
    const [, choose] = page.render(key, initial);
    choose(selected);
    page.render(key, initial);
    page.pagehide();
    assert.equal(mount(storage).render(key, initial)[0], selected, key);
  }
});

test('a saved position does not restore choices on a different project URL', () => {
  const storage = new Map();
  const page = mount(storage);
  page.render('section', '09-剧集制作');
  page.pagehide();
  assert.equal(mount(storage, 'http://localhost/#/projects/another').render('section', '00-项目定位')[0], '00-项目定位');
});

test('explicit automatic-update save continues to restore the same position', () => {
  const storage = new Map();
  const page = mount(storage);
  page.render('section', '09-剧集制作');
  page.save();
  assert.equal(mount(storage).render('section', '00-项目定位')[0], '09-剧集制作');
});
