import './CoverLibrary.css';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { AssetMediaCard } from './AssetMediaCard';
import { Groups, Original, PreviewContext } from '../components';

export function CoverLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  return <>
    <div className="toolbar"><h2>当前采用封面</h2><RecordLinks items={[value.index, value.record]} /></div>
    <div className="asset-media-grid">{value.items.map((item: RecordData) => {
      const image = item.media || item.original;
      return <AssetMediaCard key={item.name} title={item.name} revision={revision} formal item={{
        media: image && { ...image, kind: 'image', name: item.name }, version: item.version,
        statusHtml: item.statusHtml, scope: item.scope + ' · ' + item.layout,
      }}>
        {!item.media && item.original && <p className="muted">当前预览为采用原图，成品待规格处理。</p>}
        <dl className="cover-library-facts">
          <dt>登记版本</dt><dd>{item.version}</dd>
          <dt>目标规格</dt><dd>{item.targetSize} · {item.targetRatio}</dd>
          <dt>成品实测</dt><dd>{item.media ? `${item.media.width}×${item.media.height} · ${item.media.ratio}` : '待处理'}</dd>
          <dt>原图实测</dt><dd>{item.original ? `${item.original.width}×${item.original.height} · ${item.original.ratio}` : '尚未登记'}</dd>
        </dl>
        <div className="cover-library-links"><Original url={item.media?.url} label="成品原文件" />{item.media && <a href={item.media.url + '?download=true'} download>下载成品</a>}<Original url={item.original?.url} label="采用原图" />{item.original && <a href={item.original.url + '?download=true'} download>下载原图</a>}</div>
        <RecordLinks items={[item.review, item.processing]} />
      </AssetMediaCard>;
    })}</div>
    {!value.items.length && <p className="muted">尚无已登记的采用封面，可先查看候选和制作记录。</p>}
    <details className="cover-library-history" onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>候选与历史（{value.candidates.length}）</summary>
      {historyOpen && <div className="asset-media-grid">{value.candidates.map((item: RecordData) => <AssetMediaCard
        key={item.media.key} title={item.name} revision={revision} item={{
          media: { ...item.media, kind: 'image' }, generation: item.generation, recordUrl: item.record.url,
        }}>
        <p>{item.status}</p><p className="muted">实际比例：{item.media.ratio}</p>
        <Original url={item.media.url} label="候选原图" />
      </AssetMediaCard>)}</div>}
    </details>
    <Groups groups={value.groups} />
  </>;
}

function RecordLinks({ items }: { items: (RecordData | null)[] }) {
  const preview = useContext(PreviewContext);
  return <div className="cover-library-records">{items.filter(Boolean).map(item => <button className="link" key={item!.url} onClick={() => preview({ kind: item!.key.endsWith('.md') ? 'markdown' : 'text', name: item!.name, key: item!.key + new URL(item!.url, window.location.origin).hash, url: item!.url })}>{item!.name}</button>)}</div>;
}
