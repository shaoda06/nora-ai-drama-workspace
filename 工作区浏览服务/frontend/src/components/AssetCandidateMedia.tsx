import { useState } from 'react';
import type { RecordData } from '../api';
import { AssetMedia } from './AssetMedia';

export function AssetCandidateMedia({ items, revision }: { items: RecordData[]; revision: number }) {
  const grouped = new Map<string, RecordData[]>();
  for (const item of items) {
    const type = item.type === '人物多视角参考图（人物本体六视图）' ? '人物多视角参考图' : item.type || '未填写图片类型';
    if (!grouped.has(type)) grouped.set(type, []);
    grouped.get(type)!.push(item);
  }
  const order = ['人物上半身正面肖像图', '人物多视角参考图', '服装参考图', '角色多视角参考图'];
  const types = [...order.filter(type => grouped.has(type)), ...[...grouped.keys()].filter(type => !order.includes(type))];
  return items.length ? <div className="asset-candidate-types">{types.map(type => <CandidateTypeGroup key={type} type={type} items={[...grouped.get(type)!].reverse()} revision={revision} />)}</div> : <p className="muted">暂无已登记图片。</p>;
}
function CandidateTypeGroup({ type, items, revision }: { type: string; items: RecordData[]; revision: number }) {
  const [open, setOpen] = useState(false);
  return <details className="asset-candidate-type" name="asset-candidate-type" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{type}<span className="muted">（{items.length}张）</span></summary>
    {open && <AssetMedia items={items} revision={revision} />}
  </details>;
}
