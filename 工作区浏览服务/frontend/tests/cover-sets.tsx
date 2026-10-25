import { createRoot } from 'react-dom/client';
import { CoverLibrary } from '../src/components/CoverLibrary';
import '../src/style.css';

const media = (key: string) => ({ key, kind: 'image', name: key, url: '/fixtures/' + key, width: 1440, height: 1080, ratio: '4:3' });
const current = (id: string, platforms: string[], layout = '横版', scope = '系列通用') => ({
  coverId: id, name: scope + ' · ' + platforms.join('、') + ' · ' + layout + '封面', scope, layout, platforms,
  media: media(id + '-formal.svg'), original: media(id + '-候选-v02.svg'), targetSize: '1440×1080',
  targetRatio: '4:3', targetFormat: 'PNG', specBasis: '工作区交付预设；实际上传未验证',
  version: 'v02', ready: true, statusHtml: '<span>已采用</span>',
});
const record = (generation: string) => ({ name: generation, key: 'record.md', url: '/fixtures/record.md#' + generation });
const candidate = (key: string, generation: string, formal = false) => ({
  media: media(key + '.svg'), generation, status: formal ? '批准采用' : '待确认', record: record(generation),
  formal: formal ? media(key + '-delivery.svg') : null,
});
const asset = (id: string, platforms: string[], layout = '横版', scope = '系列通用') => {
  const item = current(id, platforms, layout, scope);
  const adopted = { ...candidate(id + '-候选-v02', '生成记录-002', true), current: true, formal: item.media };
  return { id, name: layout + '封面', scope, platforms, current: item, latest: adopted, hasUpdate: false,
    rounds: [{ id: 'R002', name: '配色整合', current: true, candidates: [adopted], records: [record('生成记录-002')] },
      { id: 'R001', name: '初稿', current: false, candidates: [candidate(id + '-候选-v01', '生成记录-001', true)], records: [record('生成记录-001')] }] };
};
const kuaishou = asset('COV001', ['快手']);
const latest = candidate('COV001-候选-v03', '生成记录-003');
kuaishou.latest = { ...latest, current: false };
kuaishou.hasUpdate = true;
kuaishou.rounds.unshift({ id: 'R003', name: '视线调整', current: false, candidates: [kuaishou.latest], records: [record('生成记录-003')] });
const allAssets = [kuaishou, asset('COV002', ['快手'], '竖版'), asset('COV003', ['快手', '小红书'], '横版', 'EP002'),
  asset('COV004', ['通用']), asset('COV005', ['抖音']), asset('legacy', [])];
const query = new URLSearchParams(location.search);
let assets = query.has('only-kuaishou') ? allAssets.filter(item => item.platforms.includes('快手')) : allAssets;
if (query.has('pending') || query.has('empty')) {
  const item = asset('PENDING', ['快手']);
  const pending = { ...candidate('PENDING-候选-v01', '生成记录-001'), current: false };
  assets = [{ ...item, current: { ...item.current, ready: false, media: null, original: query.has('empty') ? null : media('old-index-source.svg'), statusHtml: '<span>未确认</span>' },
    latest: query.has('empty') ? null : pending, rounds: query.has('empty') ? [] : [{ id: 'R001', name: '初稿', current: false, candidates: [pending], records: [record('生成记录-001')] }] }] as typeof allAssets;
}
createRoot(document.getElementById('root')!).render(<main><h1>封面套组测试</h1><CoverLibrary revision={1} value={{ assets,
  unassigned: [{ name: '归属未知的旧图.png', media: media('loose.svg'), record: record('生成记录-旧') }], groups: [] }} /></main>);
