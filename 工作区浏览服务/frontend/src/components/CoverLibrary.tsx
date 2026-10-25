import './CoverLibrary.css';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { AssetMediaCard } from './AssetMediaCard';
import { Dialog, Groups, PreviewContext, Rich } from '../components';
import { FileActions } from './FileActions';
import { UnderlineTabs } from './UnderlineTabs';

const coverPlatforms = ['通用', '抖音', '小红书', '快手'];

export function CoverLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [detail, setDetail] = useState<{ item: RecordData; candidate: boolean } | null>(null);
  const [platform, setPlatform] = useState(() => coverPlatforms.find(name => value.items.some((item: RecordData) => item.platforms?.includes(name))) || '通用');
  const items = value.items.filter((item: RecordData) => item.platforms?.includes(platform));
  const candidates = value.candidates.filter((item: RecordData) => item.platforms?.includes(platform));
  const unassigned = value.items.filter((item: RecordData) => !item.platforms?.length);
  const unassignedCandidates = value.candidates.filter((item: RecordData) => !item.platforms?.length);
  return <>
    <div className="toolbar"><h2>当前采用封面</h2><RecordLinks items={[value.index, value.record]} /></div>
    <UnderlineTabs label="封面平台" items={coverPlatforms.map(name => ({ value: name, label: name }))} selected={platform} onChange={name => { setPlatform(name); setHistoryOpen(false); setDetail(null); }} />
    <CoverSets items={items} revision={revision} onSelect={item => setDetail({ item, candidate: false })} />
    {!items.length && <p className="muted">{platform}暂无已登记的采用封面。</p>}
    <details className="cover-library-history" open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>候选与历史（{candidates.length}）</summary>
      {historyOpen && <CoverCandidates items={candidates} revision={revision} onSelect={item => setDetail({ item, candidate: true })} />}
    </details>
    {unassigned.length > 0 && <details className="cover-library-history">
      <summary>未登记平台的采用封面（{unassigned.length}）</summary>
      <CoverSets items={unassigned} revision={revision} onSelect={item => setDetail({ item, candidate: false })} />
    </details>}
    {unassignedCandidates.length > 0 && <details className="cover-library-history">
      <summary>未登记平台的候选与历史（{unassignedCandidates.length}）</summary>
      <CoverCandidates items={unassignedCandidates} revision={revision} onSelect={item => setDetail({ item, candidate: true })} />
    </details>}
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
          <dt>套组</dt><dd>{detail.item.setName || '未登记'}</dd>
          <dt>适用平台</dt><dd>{detail.item.platforms?.join('、') || '未登记'}</dd>
          {detail.item.specBasis && <><dt>规格依据</dt><dd>{detail.item.specBasis}</dd></>}
          <dt>目标规格</dt><dd>{detail.item.targetSize} · {detail.item.targetRatio}{detail.item.targetFormat && ` · ${detail.item.targetFormat}`}</dd>
          <dt>成品</dt><dd className="cover-library-file"><span>{detail.item.media ? `${detail.item.media.width}×${detail.item.media.height} · ${detail.item.media.ratio}` : '待处理'}</span><FileActions url={detail.item.media?.url} /></dd>
          <dt>原图</dt><dd className="cover-library-file"><span>{detail.item.original ? `${detail.item.original.width}×${detail.item.original.height} · ${detail.item.original.ratio}` : '尚未登记'}</span><FileActions url={detail.item.original?.url} /></dd>
        </dl>
        <RecordLinks items={[detail.item.review && { ...detail.item.review, name: '批准记录' }, detail.item.processing]} />
      </>}
    </Dialog>}
  </>;
}


function CoverSets({ items, revision, onSelect }: { items: RecordData[]; revision: number; onSelect: (item: RecordData) => void }) {
  const sets = new Map<string, RecordData[]>();
  for (const item of items) {
    const name = item.setName || '未登记套组';
    const entries = sets.get(name);
    if (entries) entries.push(item);
    else sets.set(name, [item]);
  }
  return <>{[...sets].map(([name, entries]) => <section key={name} aria-label={`封面套组：${name}`}>
    <div className="asset-media-grid">{entries.map(item => {
      const image = item.media || item.original;
      return <AssetMediaCard key={item.name} title={item.name} revision={revision} formal item={{
        media: image && { ...image, kind: 'image', name: item.name }, version: item.version,
        statusHtml: item.statusHtml, scope: item.scope + ' · ' + item.layout,
      }} onDetails={() => onSelect(item)} />;
    })}</div>
  </section>)}</>;
}

function CoverCandidates({ items, revision, onSelect }: { items: RecordData[]; revision: number; onSelect: (item: RecordData) => void }) {
  return <div className="asset-media-grid">{items.map(item => <AssetMediaCard
    key={item.media.key} title={item.name} revision={revision} item={{
      media: { ...item.media, kind: 'image' }, generation: item.generation, userState: item.status,
    }} onDetails={() => onSelect(item)} />)}</div>;
}

function RecordLinks({ items }: { items: (RecordData | null)[] }) {
  const preview = useContext(PreviewContext);
  return <div className="cover-library-records">{items.filter(Boolean).map(item => <button className="link" key={item!.url} onClick={() => preview({ kind: item!.key.endsWith('.md') ? 'markdown' : 'text', name: item!.name, key: item!.key + new URL(item!.url, window.location.origin).hash, url: item!.url })}>{item!.name}</button>)}</div>;
}
