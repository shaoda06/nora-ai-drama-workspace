import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = require('react/jsx-runtime');
const source = readFileSync(process.env.NORA_VIDEO_SOURCE || new URL('../frontend/src/components/SegmentVideo.tsx', import.meta.url), 'utf8');

function fixture({ frameAPI = true, qualityAPI = true } = {}) {
  let now = 0, id = 0;
  const intervals = new Map(), callbacks = new Map();
  const document = { hidden: false };
  class Video extends EventTarget {
    currentTime = 0; duration = 14; readyState = 4; paused = false; ended = false; error = null;
    volume = 0.4; muted = true; playbackRate = 1.5; frames = 0;
    requestVideoFrameCallback(callback) { callbacks.set(++id, callback); return id; }
    cancelVideoFrameCallback(value) { callbacks.delete(value); }
    getVideoPlaybackQuality() { return { totalVideoFrames: this.frames }; }
    pause() { this.paused = true; }
  }
  const video = new Video();
  if (!frameAPI) video.requestVideoFrameCallback = undefined;
  if (!qualityAPI) video.getVideoPlaybackQuality = undefined;
  const states = [], effects = [];
  let hook = 0;
  const effect = (callback, deps) => {
    const index = hook++, previous = states[index];
    if (!previous || deps.some((value, i) => value !== previous.deps[i])) effects.push(() => {
      previous?.cleanup?.(); states[index] = { deps, cleanup: callback() };
    });
  };
  const react = {
    useEffect: effect, useLayoutEffect: effect,
    useRef(initial) { const index = hook++; states[index] ??= { current: initial }; return states[index]; },
    useState(initial) { const index = hook++; if (!(index in states)) states[index] = initial;
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }]; },
    useImperativeHandle(ref, create) { ref.current = create(); },
  };
  const exports = {}, queryClient = { invalidateQueries() {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { exports, require: name => ({ react, 'react/jsx-runtime': jsx,
      '@tanstack/react-query': { useQuery: () => ({}), useQueryClient: () => queryClient } }[name] || {}),
      performance: { now: () => now }, document, window: { setInterval(callback) { intervals.set(++id, callback); return id; }, clearInterval: value => intervals.delete(value) } });
  const tick = (seconds, { moving = true, present = false } = {}) => {
    for (let i = 0; i < seconds; i++) {
      now += 1000;
      if (moving) { video.currentTime += 1; video.frames += 24; }
      if (present) for (const [key, callback] of [...callbacks]) { callbacks.delete(key); callback(); }
      for (const callback of [...intervals.values()]) callback();
    }
  };
  const find = (tree, type) => {
    if (!tree || typeof tree !== 'object') return;
    if (tree.type === type) return tree;
    for (const child of [tree.props?.children].flat(Infinity)) { const result = find(child, type); if (result) return result; }
  };
  const props = { current: { key: 'P005-R006', url: '/same-file.mp4', stage: '一采', run: 'R006', candidateNumber: 6,
    fileRevision: 'original-revision', deliveryStatus: '已取回' }, onTimeChange() {},
    wide: false, onToggleWide() {}, retainSource: () => () => {}, playerRef: {} };
  const render = () => {
    hook = 0;
    const tree = exports.SegmentVideo(props), media = find(tree, 'video');
    if (media) media.props.ref.current = video;
    while (effects.length) effects.shift()();
    return { tree, media, find: type => find(tree, type) };
  };
  return { ...exports, video, tick, document, intervals, callbacks, props, render };
}

test('advancing audio clock with ready data but no presented frames requests one recovery', () => {
  const app = fixture(); let recovered = 0;
  app.watchVideoPlayback(app.video, () => recovered++);
  app.tick(2); assert.equal(recovered, 0);
  app.tick(1); assert.equal(recovered, 1);
  app.tick(5); assert.equal(recovered, 1);
});

test('healthy frames, paused playback and background tabs are not reloaded', () => {
  const app = fixture(); let recovered = 0;
  app.watchVideoPlayback(app.video, () => recovered++);
  app.tick(6, { present: true });
  app.video.paused = true; app.tick(5, { moving: false });
  app.video.paused = false; app.video.dispatchEvent(new Event('playing'));
  app.document.hidden = true; app.tick(5);
  app.document.hidden = false; app.tick(2, { present: true });
  assert.equal(recovered, 0);
});

test('network stalls and media errors recover after a bounded wait', () => {
  for (const event of ['waiting', 'stalled', 'error']) {
    const app = fixture(); let recovered = 0;
    app.video.readyState = 2;
    if (event === 'error') { app.video.error = { code: 2 }; app.video.paused = true; }
    app.watchVideoPlayback(app.video, () => recovered++);
    app.video.dispatchEvent(new Event(event)); app.tick(3, { moving: false });
    assert.equal(recovered, 1, event);
  }
});

test('frame-count fallback detects a stopped video track without frame callbacks', () => {
  const app = fixture({ frameAPI: false }); let recovered = 0;
  app.watchVideoPlayback(app.video, () => recovered++);
  app.tick(4); assert.equal(recovered, 0);
  app.video.getVideoPlaybackQuality = () => ({ totalVideoFrames: 96 });
  app.tick(3); assert.equal(recovered, 1);
});

test('cleanup removes frame callbacks, listeners and timers for the old candidate', () => {
  const app = fixture(); let recovered = 0;
  const cleanup = app.watchVideoPlayback(app.video, () => recovered++);
  cleanup(); app.video.dispatchEvent(new Event('error')); app.tick(5);
  assert.equal(app.intervals.size, 0); assert.equal(app.callbacks.size, 0); assert.equal(recovered, 0);
});

test('recovery rebuilds only the same video and restores time, playback and volume', () => {
  const app = fixture(); const initial = app.render();
  app.video.paused = false; app.video.currentTime = 4; app.video.dispatchEvent(new Event('playing'));
  app.tick(3);
  const retried = app.render();
  assert.notEqual(retried.media.key, initial.media.key);
  assert.equal(retried.media.props.src, '/same-file.mp4');
  assert.equal(retried.media.props.autoPlay, true);
  app.video.currentTime = 0; app.video.volume = 1; app.video.muted = false; app.video.playbackRate = 1;
  retried.media.props.onLoadedMetadata({ currentTarget: app.video });
  assert.equal(app.video.currentTime, 7); assert.equal(app.video.volume, 0.4);
  assert.equal(app.video.muted, true); assert.equal(app.video.playbackRate, 1.5);
});

test('repeated failure stops after two automatic reloads and keeps a local retry action', () => {
  const app = fixture(); let failures = 0; app.props.onError = () => failures++;
  app.render();
  for (let i = 0; i < 3; i++) {
    app.video.paused = false; app.video.dispatchEvent(new Event('playing')); app.tick(3); app.render();
  }
  assert.equal(failures, 1);
  const stopped = app.render();
  assert.equal(stopped.media.key, 'original-revision:2');
  assert.ok(JSON.stringify(stopped.tree).includes('重新加载视频'));
});
