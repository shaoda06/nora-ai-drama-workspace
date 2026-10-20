import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../frontend/src/refreshPosition.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

// Exercise the real hook's setter against React's Object.is state bailout.
// No browser storage, project files, or production requests are modified.
function mount() {
  let entry;
  let updates = 0;
  const exports = {};
  const react = {
    useState(initial) {
      entry ??= initial();
      return [entry, next => {
        const value = typeof next === 'function' ? next(entry) : next;
        if (!Object.is(entry, value)) { entry = value; updates++; }
      }];
    },
    useCallback: callback => callback,
    useEffect() {},
  };
  vm.runInNewContext(compiled, {
    exports, require: name => { assert.equal(name, 'react'); return react; },
    sessionStorage: { getItem: () => null, removeItem() {} },
    window: { location: { href: 'http://localhost/#/projects/fixture' } },
  });
  return { render: (key, initial) => exports.useRefreshState(key, initial), updates: () => updates };
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
