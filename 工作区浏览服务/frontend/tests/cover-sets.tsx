import { createRoot } from 'react-dom/client';
import { CoverLibrary } from '../src/components/CoverLibrary';
import '../src/style.css';

const media = { key: '封面.png', kind: 'image', name: '封面', url: '/fixtures/cover.svg', width: 1440, height: 1080, ratio: '4:3' };
const item = { media, original: media, targetSize: '1440×1080', targetRatio: '4:3', targetFormat: 'PNG', specBasis: '用户指定；未核实为平台官方规格', scope: '系列通用', version: 'v01', statusHtml: '<span>已采用</span>' };
const items = [
  { ...item, name: '系列通用 · 快手 · 横版封面', setName: '系列通用', platforms: ['快手'], layout: '横版' },
  { ...item, name: '系列通用 · 快手 · 竖版封面', setName: '系列通用', platforms: ['快手'], layout: '竖版' },
  { ...item, name: 'EP002 · 快手、小红书 · 横版封面', setName: 'EP002', platforms: ['快手', '小红书'], layout: '横版' },
  { ...item, name: '通用设计 · 通用 · 横版封面', setName: '通用设计', platforms: ['通用'], layout: '横版' },
  { ...item, name: '抖音设计 · 抖音 · 横版封面', setName: '抖音设计', platforms: ['抖音'], layout: '横版' },
  { ...item, name: '历史封面', setName: '', platforms: [], layout: '竖版' },
];
const candidates = [
  { name: '快手候选', media: { ...media, key: '快手候选.png' }, generation: '生成记录-001', status: '待确认', platforms: ['快手'] },
  { name: '多平台候选', media: { ...media, key: '多平台候选.png' }, generation: '生成记录-002', status: '待确认', platforms: ['抖音', '小红书'] },
  { name: '旧候选', media: { ...media, key: '旧候选.png' }, generation: '生成记录-003', status: '待确认', platforms: [] },
];
const onlyKuaishou = new URLSearchParams(location.search).has('only-kuaishou');
createRoot(document.getElementById('root')!).render(<main><h1>封面套组测试</h1><CoverLibrary revision={1} value={{ items: onlyKuaishou ? items.filter(item => item.platforms.includes('快手')) : items, candidates, groups: [] }} /></main>);
