import './CoverLibrary.css';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { AssetMediaCard } from './AssetMediaCard';
import { Dialog, Groups, PreviewContext, Rich } from '../components';
import { FileActions } from './FileActions';
import { UnderlineTabs } from './UnderlineTabs';

const coverPlatforms = ['通用', '抖音', '小红书', '快手'];
type DetailTab = 'current' | 'latest' | 'history';

export function CoverLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const [platform, setPlatform] = useState(() => coverPlatforms.find(name => value.assets.some((asset: RecordData) => asset.platforms.includes(name))) || '通用');
  const [detail, setDetail] = useState<{ id: string; tab: DetailTab } | null>(null);
  const assets = value.assets.filter((asset: RecordData) => asset.platforms.includes(platform));
  const unassignedAssets = value.assets.filter((asset: RecordData) => !asset.platforms.length);
  const selected = detail && value.assets.find((asset: RecordData) => asset.id === detail.id);
  const groups = new Map<string, RecordData[]>();
  for (const asset of assets) {
    const list = groups.get(asset.scope) || [];
    list.push(asset);
    groups.set(asset.scope, list);
  }
  const open = (asset: RecordData) => setDetail({ id: asset.id, tab: asset.current.ready ? 'current' : asset.latest ? 'latest' : 'history' });
  return <>
    <div className="toolbar"><h2>封面</h2><RecordLinks items={[value.index, value.record]} /></div>
    <UnderlineTabs label="封面平台" items={coverPlatforms.map(name => ({ value: name, label: name }))} selected={platform} onChange={name => { setPlatform(name); setDetail(null); }} />
    {[...groups].map(([scope, entries]) => <section key={scope} aria-label={`${scope}封面`}>
      {groups.size > 1 && <h3>{scope}</h3>}
      <div className="asset-media-grid">{[...entries].sort((a, b) => a.current.layout.localeCompare(b.current.layout, 'zh')).map(asset => {
        const current = asset.current, media = current.ready ? current.media : asset.latest?.media || current.original || current.media;
        return <AssetMediaCard key={asset.id} title={asset.name} revision={revision} formal={current.ready} item={{
          media: media && { ...media, kind: 'image', name: asset.name },
          version: current.ready ? current.version : undefined,
          statusHtml: current.ready ? current.statusHtml + (asset.hasUpdate ? ' · 有新候选待确认' : '') : '<span>尚无正式版</span>',
          scope: current.scope, emptyLabel: '尚未生成图片',
        }} onDetails={() => open(asset)} />;
      })}</div>
    </section>)}
    {!assets.length && <p className="muted">{platform}暂无已登记的封面。</p>}
    {(value.unassigned.length > 0 || unassignedAssets.length > 0) && <details className="cover-library-history">
      <summary>待归类资料（{value.unassigned.length + unassignedAssets.length}）</summary>
      <p className="muted">这些资料尚未关联到明确的封面，保留原文件及制作记录。</p>
      <ul className="cover-unassigned">{unassignedAssets.map((asset: RecordData) => <li key={asset.id}><button className="link" onClick={() => open(asset)}>{asset.current.name}</button><span className="muted">待补平台</span></li>)}
        {value.unassigned.map((item: RecordData) => <li key={item.media.key}><span>{item.name}</span><FileActions url={item.media.url} /><RecordLinks items={[item.record]} /></li>)}
      </ul>
    </details>}
    <Groups groups={value.groups} />
    {selected && detail && <Dialog title={`${selected.name} · 详情`} close={() => setDetail(null)}>
      <UnderlineTabs label="封面详情" items={[
        { value: 'current' as DetailTab, label: '当前正式' },
        ...(selected.latest && (!selected.current.ready || selected.hasUpdate) ? [{ value: 'latest' as DetailTab, label: '最新候选' }] : []),
        { value: 'history' as DetailTab, label: `版本记录（${selected.rounds.length}）` },
      ]} selected={detail.tab} onChange={tab => setDetail({ id: selected.id, tab })} />
      {detail.tab === 'current' && <CurrentCover item={selected.current} />}
      {detail.tab === 'latest' && selected.latest && <><CoverCandidate item={selected.latest} revision={revision} title="最新候选" /><RecordLinks items={[selected.latest.record]} /></>}
      {detail.tab === 'history' && <div className="cover-version-list">{selected.rounds.map((round: RecordData) => <details className="cover-version" key={round.id}>
        <summary><strong>{round.name}</strong> <span className="muted">{round.id}{round.current ? ' · 当前正式' : ''}</span></summary>
        <div className="cover-version-body">
          {!round.candidates.length && <p className="muted">本轮尚无可预览图片，执行情况见制作记录。</p>}
          <div className="asset-media-grid">{round.candidates.map((candidate: RecordData, index: number) => <CoverCandidate key={candidate.media.key} item={candidate} revision={revision} title={round.candidates.length > 1 ? `候选${index + 1}` : '本轮原图'} />)}</div>
          <RecordLinks items={round.records} />
        </div>
      </details>)}{!selected.rounds.length && <p className="muted">尚无版本记录。</p>}</div>}
    </Dialog>}
  </>;
}

function CurrentCover({ item }: { item: RecordData }) {
  return <>
    <Rich html={item.statusHtml} />
    {!item.ready && <p className="muted">尚无已采用且达到目标规格的正式版。</p>}
    <dl className="cover-library-facts">
      <dt>封面编号</dt><dd>{item.coverId || '未登记'}</dd>
      <dt>适用平台</dt><dd>{item.platforms.join('、') || '未登记'}</dd>
      <dt>适用范围</dt><dd>{item.scope}</dd>
      {item.specBasis && <><dt>规格依据</dt><dd>{item.specBasis}</dd></>}
      <dt>目标规格</dt><dd>{item.targetSize} · {item.targetRatio}{item.targetFormat && ` · ${item.targetFormat}`}</dd>
      <dt>成品</dt><dd className="cover-library-file"><span>{item.media ? `${item.media.width}×${item.media.height} · ${item.media.ratio}` : '待处理'}</span><FileActions url={item.media?.url} /></dd>
      <dt>原图</dt><dd className="cover-library-file"><span>{item.original ? `${item.original.width}×${item.original.height} · ${item.original.ratio}` : '尚未登记'}</span><FileActions url={item.original?.url} /></dd>
    </dl>
    <RecordLinks items={[item.review && { ...item.review, name: '批准记录' }, item.processing]} />
  </>;
}

function CoverCandidate({ item, revision, title }: { item: RecordData; revision: number; title: string }) {
  return <section>
    <AssetMediaCard title={title} revision={revision} item={{ media: { ...item.media, kind: 'image', name: title }, userState: item.status }} />
    {item.formal && <dl className="cover-library-facts"><dt>本轮成品</dt><dd className="cover-library-file"><span>{item.formal.width}×{item.formal.height} · {item.formal.ratio}</span><FileActions url={item.formal.url} /></dd></dl>}
    <RecordLinks items={[item.review && { ...item.review, name: '审阅记录' }, item.processing]} />
  </section>;
}

function RecordLinks({ items }: { items: (RecordData | null)[] }) {
  const preview = useContext(PreviewContext);
  return <div className="cover-library-records">{items.filter(Boolean).map(item => <button className="link" key={item!.url} onClick={() => preview({ kind: item!.key.endsWith('.md') ? 'markdown' : 'text', name: item!.name, key: item!.key + new URL(item!.url, window.location.origin).hash, url: item!.url })}>{item!.name}</button>)}</div>;
}
