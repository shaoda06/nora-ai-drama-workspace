import './CoverLibrary.css';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { AssetMediaCard } from './AssetMediaCard';
import { Dialog, Groups, PreviewContext, Rich } from '../components';
import { FileActions } from './FileActions';

export function CoverLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [detail, setDetail] = useState<{ item: RecordData; candidate: boolean } | null>(null);
  return <>
    <div className="toolbar"><h2>当前采用封面</h2><RecordLinks items={[value.index, value.record]} /></div>
    <div className="asset-media-grid">{value.items.map((item: RecordData) => {
      const image = item.media || item.original;
      return <AssetMediaCard key={item.name} title={item.name} revision={revision} formal item={{
        media: image && { ...image, kind: 'image', name: item.name }, version: item.version,
        statusHtml: item.statusHtml, scope: item.scope + ' · ' + item.layout,
      }} onDetails={() => setDetail({ item, candidate: false })} />;
    })}</div>
    {!value.items.length && <p className="muted">尚无已登记的采用封面，可先查看候选和制作记录。</p>}
    <details className="cover-library-history" onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>候选与历史（{value.candidates.length}）</summary>
      {historyOpen && <div className="asset-media-grid">{value.candidates.map((item: RecordData) => <AssetMediaCard
        key={item.media.key} title={item.name} revision={revision} item={{
          media: { ...item.media, kind: 'image' }, generation: item.generation, userState: item.status,
        }} onDetails={() => setDetail({ item, candidate: true })} />)}</div>}
    </details>
    <Groups groups={value.groups} />
    {detail && <Dialog title={`${detail.item.name} · 详情`} close={() => setDetail(null)}>
      {detail.candidate ? <>
        <p>{detail.item.status}</p>
        <dl className="cover-library-facts"><dt>原图</dt><dd className="cover-library-file"><span>{detail.item.media.width}×{detail.item.media.height} · {detail.item.media.ratio}</span><FileActions url={detail.item.media.url} /></dd></dl>
        <RecordLinks items={[detail.item.record]} />
      </> : <>
        <Rich html={detail.item.statusHtml} />
        {!detail.item.media && detail.item.original && <p className="muted">当前预览为采用原图，成品待规格处理。</p>}
        <dl className="cover-library-facts">
          <dt>目标规格</dt><dd>{detail.item.targetSize} · {detail.item.targetRatio}</dd>
          <dt>成品</dt><dd className="cover-library-file"><span>{detail.item.media ? `${detail.item.media.width}×${detail.item.media.height} · ${detail.item.media.ratio}` : '待处理'}</span><FileActions url={detail.item.media?.url} /></dd>
          <dt>原图</dt><dd className="cover-library-file"><span>{detail.item.original ? `${detail.item.original.width}×${detail.item.original.height} · ${detail.item.original.ratio}` : '尚未登记'}</span><FileActions url={detail.item.original?.url} /></dd>
        </dl>
        <RecordLinks items={[detail.item.review && { ...detail.item.review, name: '批准记录' }, detail.item.processing]} />
      </>}
    </Dialog>}
  </>;
}

function RecordLinks({ items }: { items: (RecordData | null)[] }) {
  const preview = useContext(PreviewContext);
  return <div className="cover-library-records">{items.filter(Boolean).map(item => <button className="link" key={item!.url} onClick={() => preview({ kind: item!.key.endsWith('.md') ? 'markdown' : 'text', name: item!.name, key: item!.key + new URL(item!.url, window.location.origin).hash, url: item!.url })}>{item!.name}</button>)}</div>;
}
