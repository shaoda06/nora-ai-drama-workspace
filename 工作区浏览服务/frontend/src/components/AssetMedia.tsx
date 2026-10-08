import type { RecordData } from '../api';
import { AssetMediaCard } from './AssetMediaCard';

export function AssetMedia({ items, revision, formal = false }: { items: RecordData[]; revision: number; formal?: boolean }) {
  return items.length ? <div className="asset-media-grid">{items.map(item => <AssetMediaCard key={item.media?.key || item.recordUrl} title={[item.stage, item.type, item.state, item.costume].filter(Boolean).join(' · ') || '参考图'} item={item} revision={revision} formal={formal} />)}</div> : <p className="muted">暂无已登记图片。</p>;
}
