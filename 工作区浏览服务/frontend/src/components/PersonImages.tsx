import { useState } from 'react';
import type { RecordData } from '../api';
import { AssetMedia } from './AssetMedia';
import { TabSelect } from './TabSelect';

export const personImageTabs = ['人物基础', '服装', '穿衣造型'];

export function personImageCategory(item: RecordData) {
  if (item.type === '服装参考图') return '服装';
  if (item.type === '角色多视角参考图') return '穿衣造型';
  return '人物基础';
}

// 只编排人物资产登记的展示，不改写图片身份和审批状态。
export function PersonImages({ detail, category, revision }: { detail: RecordData; category: string; revision: number }) {
  const [wardrobe, setWardrobe] = useState('');
  const outfit = (item: RecordData) => [item.stage, item.state, item.costume || '未填写服装状态'].filter(Boolean).join(' · ');
  const all: RecordData[] = [...detail.formal, ...detail.candidates].filter(item => personImageCategory(item) === category);
  const outfits = [...new Set(all.map(outfit))];
  const matches = (item: RecordData) => personImageCategory(item) === category && (!wardrobe || outfit(item) === wardrobe);
  const formal: RecordData[] = detail.formal.filter(matches);
  const candidates: RecordData[] = detail.candidates.filter(matches);
  const adopted = formal.filter(item => item.approved);
  const otherFormal = formal.filter(item => !item.approved);
  const history = candidates.filter(item => /^(已结束未采用|已被替换／归档|不采用|未采用)(?:$|[。；，\s])/.test(item.userDecision));
  const current = candidates.filter(item => !history.includes(item));
  return <section aria-label={`${category}图片`}>
    {category !== '人物基础' && <div className="toolbar"><TabSelect label="衣装分组" selected={wardrobe} onChange={setWardrobe} items={[{ value: '', label: '全部衣装' }, ...outfits.map(value => ({ value, label: value }))]} /></div>}
    <h3>已采用图片（{adopted.length}张）</h3>
    {adopted.length ? <AssetMedia items={adopted} revision={revision} formal /> : <p className="muted">暂无已采用图片。</p>}
    <ImageArchive key={`${wardrobe}-candidates`} title="候选与审阅" items={[...current].reverse()} revision={revision} />
    <ImageArchive key={`${wardrobe}-history`} title="历史版本" items={[...history].reverse()} revision={revision} />
    {otherFormal.length > 0 && <ImageArchive key={`${wardrobe}-other`} title="其他已登记图片" items={otherFormal} revision={revision} formal />}
  </section>;
}

function ImageArchive({ title, items, revision, formal = false }: { title: string; items: RecordData[]; revision: number; formal?: boolean }) {
  const [open, setOpen] = useState(false);
  return <details className="asset-candidate-type" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{title}<span className="muted">（{items.length}张）</span></summary>
    {open && <AssetMedia items={items} revision={revision} formal={formal} />}
  </details>;
}
