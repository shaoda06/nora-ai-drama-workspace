import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { setImmediate as settle } from 'node:timers/promises';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../frontend/src/components/TaskSidebar.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

// Use the actual component's query with the installed QueryObserver. Each client
// represents an independent page; all transport and timing stay in this test.
globalThis.window = {};
const { QueryClient, QueryObserver, focusManager } = require('@tanstack/react-query');

test('task polling supports eight pages, pauses when hidden, deduplicates slow reads and recovers', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let options;
  const requests = [];
  const exports = {};
  const react = {
    useState: initial => [initial, () => {}], useRef: initial => ({ current: initial }),
    useEffect() {}, useCallback: callback => callback,
  };
  vm.runInNewContext(compiled, {
    exports,
    require: name => name === 'react' ? react : name === '@tanstack/react-query' ? {
      useQuery(value) { options = value; return { data: undefined, isError: false, refetch() {} }; },
    } : name === 'react/jsx-runtime' ? { jsx() {}, jsxs() {} }
      : name === './LocalQueueCard' ? { localQueueStates: { queued: '排队中', paused: '暂停中', history: '历史' } } : {},
    fetch: (url, { signal }) => {
      assert.equal(url, '/api/comfy/tasks?include_history=false');
      return new Promise((resolve, reject) => {
        const request = { resolve, signal };
        requests.push(request);
        signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      });
    },
    EventSource() { assert.fail('task progress must not hold an SSE connection'); },
  });
  exports.TaskSidebar();
  assert.ok(options, 'TaskSidebar must use the short-request query');
  const clients = Array.from({ length: 8 }, () => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  focusManager.setFocused(true);
  clients.forEach(client => client.mount());
  const observers = clients.map(client => new QueryObserver(client, options));
  const unsubscribe = observers.map(observer => observer.subscribe(() => {}));
  t.after(() => {
    unsubscribe.forEach(stop => stop()); clients.forEach(client => { client.unmount(); client.clear(); });
    focusManager.setFocused(undefined); delete globalThis.window; t.mock.timers.reset();
  });
  const finish = (start, failed = false) => requests.slice(start).forEach(request => request.resolve({
    ok: !failed, json: async () => ({ tasks: [], local_tasks: [], remote_nodes: [], local_counts: {}, history_updated_at: {} }),
  }));
  assert.equal(requests.length, 8);
  finish(0); await settle();
  assert.ok(observers.every(observer => observer.getCurrentResult().isSuccess));

  t.mock.timers.tick(3000); await settle();
  assert.equal(requests.length, 16, 'visible pages refresh');
  t.mock.timers.tick(9000); await settle();
  assert.equal(requests.length, 16, 'slow requests do not stack up');
  finish(8); await settle();

  focusManager.setFocused(false);
  t.mock.timers.tick(9000); await settle();
  assert.equal(requests.length, 16, 'hidden pages stop periodic reads');
  focusManager.setFocused(true); await settle();
  assert.equal(requests.length, 24, 'returning to a page immediately refreshes');
  finish(16, true); await settle();
  assert.ok(observers.every(observer => observer.getCurrentResult().isError));
  assert.ok(observers.every(observer => observer.getCurrentResult().data), 'last known snapshot remains available');
  t.mock.timers.tick(3000); await settle();
  assert.equal(requests.length, 32, 'failed reads retry on the next polling interval');
  finish(24); await settle();
  assert.ok(observers.every(observer => observer.getCurrentResult().isSuccess));

  t.mock.timers.tick(3000); await settle();
  const pending = requests.slice(32);
  assert.equal(pending.length, 8);
  unsubscribe.forEach(stop => stop()); await settle();
  assert.ok(pending.every(request => request.signal.aborted), 'leaving the page cancels pending reads');
});
