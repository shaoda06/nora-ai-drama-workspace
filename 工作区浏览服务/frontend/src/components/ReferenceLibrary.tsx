import { useEffect, useRef, useState } from 'react';
import type { FileItem, RecordData } from '../api';
import { FileTree, Original, Rich } from '../components';
import { SearchField } from './SearchField';
import { ReferenceMediaCard } from './ReferenceMediaCard';
import { AudioPreviewButton, useAudioPreview } from './AudioPreviewButton';

export function ReferenceLibrary({ value, revision, active, asset, onAssetChange }: {
  value: RecordData; revision: number; active: boolean;
  asset: { id: string; name: string } | null; onAssetChange: (asset: { id: string; name: string } | null) => void;
}) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const audio = value.key === '07-参考音频';
  const preview = useAudioPreview(active, asset?.id || null, revision);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => { if (!active) video.current?.pause(); return () => { video.current?.pause(); }; }, [active, asset?.id]);
  const items: FileItem[] = value.children.filter((item: FileItem) => item.kind === 'reference');
  const other: FileItem[] = value.children.filter((item: FileItem) => item.kind !== 'reference');
  const selected = asset && items.find(item => item.name.split(' · ')[0] === asset.id);
  const matched = items.filter(item => (!category || item.category === category) && `${item.name} ${item.media?.name || ''} ${item.summary}`.toLowerCase().includes(search.toLowerCase()));
  const select = (item: FileItem) => onAssetChange({ id: item.name.split(' · ')[0], name: item.name.split(' · ').slice(1).join(' · ') });
  const button = (item: FileItem) => <AudioPreviewButton name={item.name} enabled={!!item.media} playing={preview.playingId === item.key} progress={preview.currentId === item.key ? preview.progress : 0} onClick={() => preview.toggle(item.key!, item.media!.url!)} />;
  return <>{audio && preview.player}{selected ? <>
    <div className="reference-detail-heading"><h2>{selected.name}</h2>{audio && button(selected)}</div>
    {selected.media ? !audio && <video ref={video} className="reference-video" controls preload="metadata" src={selected.media.url + `?v=${revision}`} /> : <p className="muted">索引关联的媒体文件不存在。</p>}
    <dl className="reference-details">
      <dt>文件名：</dt><dd>{selected.media?.name || '文件未就绪'} <Original url={selected.media?.url} label="媒体原文件" /></dd>
      <dt>批准状态：</dt><dd><Rich html={selected.approvalHtml} /></dd>
      <dt>分类：</dt><dd>{selected.category}</dd>
      <dt>实测时长：</dt><dd>{selected.duration}</dd>
      <dt>用途与适用范围：</dt><dd>{selected.summary}</dd>
      <dt>来源及使用授权：</dt><dd><Rich html={selected.sourceHtml} /></dd>
      <dt>版本与采用依据：</dt><dd><Rich html={selected.statusHtml} /></dd>
    </dl>
  </> : <>
    <div className="toolbar"><SearchField label="搜索参考素材" placeholder="搜索文件名、名称" value={search} onChange={setSearch} /><select aria-label="参考素材分类" value={category} onChange={event => setCategory(event.target.value)}><option value="">全部分类</option>{value.categories.map((name: string) => <option key={name}>{name}</option>)}</select></div>
    <div className="reference-media-list">{matched.map(item => <ReferenceMediaCard key={item.key} item={item} audio={audio} playing={preview.playingId === item.key} progress={preview.currentId === item.key ? preview.progress : 0} onPlay={() => preview.toggle(item.key!, item.media!.url!)} onSelect={() => select(item)} />)}</div>
    {!matched.length && <p className="muted">暂无匹配的参考素材。</p>}<FileTree items={other} />
  </>}</>;
}
