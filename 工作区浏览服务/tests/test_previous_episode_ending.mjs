import assert from 'node:assert/strict';
import { test } from 'node:test';
import { previousEpisodeEnding } from '../frontend/src/previousEpisodeEnding.ts';

const segment = id => ({ id, duration: 10, scriptHtml: '', videos: [] });

test('共用片头片尾没有上一集关联', () => {
  for (const unit of ['片头', '片尾']) assert.equal(previousEpisodeEnding([], unit), null);
});

test('第一集不显示上集入口', () => {
  assert.equal(previousEpisodeEnding([{ name: 'EP000' }], 'EP001'), null);
});

test('末段按剧本场次和分镜索引顺序读取，不能按编号大小判断', () => {
  const last = segment('P002');
  const episodes = [{ name: 'EP002', scenes: ['C010', 'C003'], segments: {
    C010: [segment('P099')], C003: [segment('P020'), last],
  } }];
  const result = previousEpisodeEnding(episodes, 'EP003');
  assert.equal(result.episode, 'EP002');
  assert.equal(result.scene, 'C003');
  assert.equal(result.segment, last);
  assert.deepEqual(result.segments, episodes[0].segments.C003);
});

test('直接上一集缺失时保留缺项入口，不跳过到更早剧集', () => {
  const result = previousEpisodeEnding([{ name: 'EP001', scenes: ['C001'], segments: { C001: [segment('P007')] } }], 'EP003');
  assert.equal(result.episode, 'EP002');
  assert.equal(result.segment, undefined);
});

test('上一集最终场次尚无分段时，不拿前一场冒充结尾', () => {
  const result = previousEpisodeEnding([{ name: 'EP002', scenes: ['C001', 'C002'], segments: {
    C001: [segment('P012')], C002: [],
  } }], 'EP003');
  assert.equal(result.scene, 'C002');
  assert.equal(result.segment, undefined);
});

test('末段没有生成视频时仍保留准确的分段身份', () => {
  const last = segment('P012');
  const result = previousEpisodeEnding([{ name: 'EP002', scenes: ['C001'], segments: { C001: [last] } }], 'EP003');
  assert.equal(result.segment, last);
  assert.equal(result.segment.videos.length, 0);
});

test('集号保留项目已有位数，返回原有版本集合', () => {
  const last = segment('P003');
  last.videos = [{ key: 'older' }, { key: 'newer' }];
  const result = previousEpisodeEnding([{ name: 'EP0999', scenes: ['C001'], segments: { C001: [last] } }], 'EP1000');
  assert.equal(result.episode, 'EP0999');
  assert.equal(result.segment.videos, last.videos);
});
