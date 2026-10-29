import { FileTree } from '../components';
import { useMemo, useState } from 'react';
import type { FileItem } from '../api';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { UnderlineTabs } from './UnderlineTabs';
import { FloatingMessage } from './Notifications';
import { DownloadButton } from './DownloadButton';
import './ReleaseFilms.css';

const releaseOrder = new Map([['片头', 0], ['片尾', 1]]);

export function releaseVideos(items: FileItem[]): FileItem[] {
  return items.flatMap(item => item.children || item.files ? releaseVideos(item.children || item.files!) : item.kind === 'video' ? [item] : [])
    .sort((a, b) => (releaseOrder.get(a.name.replace(/\.[^.]+$/, '')) ?? 2)
      - (releaseOrder.get(b.name.replace(/\.[^.]+$/, '')) ?? 2)
      || (a.key || a.name).localeCompare(b.key || b.name, 'zh-CN', { numeric: true }));
}

export function ReleaseFilms({ items, active = true }: { items: FileItem[]; active?: boolean }) {
  const categories = useMemo(() => {
    const groups = items.filter(item => item.children || item.files).map(item => ({
      value: item.name, label: item.name, files: item.children || item.files!,
      videos: releaseVideos(item.children || item.files!),
    })).sort((a, b) => (releaseOrder.get(a.value) ?? 2) - (releaseOrder.get(b.value) ?? 2));
    const loose = items.filter(item => !item.children && !item.files);
    if (loose.length) groups.push({ value: '其他文件', label: '其他文件', files: loose, videos: releaseVideos(loose) });
    return groups;
  }, [items]);
  const [category, setCategory] = useState('片头');
  const current = categories.find(item => item.value === category) || categories[0];
  if (!active) return null;
  if (!current) return <p className="muted">暂无成片交付资料。</p>;
  return <div className="release-films">
    <UnderlineTabs label="成片交付分类" items={categories} selected={current.value} onChange={setCategory} />
    <ReleaseFilmList key={current.value} videos={current.videos} category={current.label} />
    <FileTree key={current.value + 'files'} showStatus={false} showOriginal={false} items={current.files} />
  </div>;
}

function ReleaseFilmList({ videos, category }: { videos: FileItem[]; category: string }) {
  const [selected, setSelected] = useState('');
  const index = Math.max(0, videos.findIndex(item => (item.key || item.url) === selected));
  const page = Math.floor(index / 5) + 1;
  const current = videos[index];
  return <>
    <div className="release-films-toolbar">
      <Pagination compact fitContent pageSize={5} page={page} total={videos.length} change={page => setSelected(videos[(page - 1) * 5].key || videos[(page - 1) * 5].url!)}>
        <TabNav scrollable label="成片交付选集" items={videos.slice((page - 1) * 5, page * 5).map(item => ({ value: item.key || item.url!, label: item.name.replace(/\.[^.]+$/, '') }))} selected={current?.key || current?.url || ''} onChange={setSelected} />
      </Pagination>
      <div className="release-films-download"><DownloadButton key={current?.key || current?.url || 'empty'} url={current?.url || null} filename={current?.name} label="下载" title={current ? `下载${current.name}` : `暂无${category}视频`} /></div>
    </div>
    {current ? <ReleaseFilmPlayer key={current.key || current.url} item={current} /> : <p className="muted">暂无{category}视频。</p>}
  </>;
}

function ReleaseFilmPlayer({ item }: { item: FileItem }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  return <>
    <video key={attempt} className="release-films-player" aria-label={item.name} controls preload="metadata" src={item.url} onError={() => setFailed(true)} />
    {failed && <FloatingMessage tone="error">{item.name} 无法播放。<button onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>重新加载视频</button></FloatingMessage>}
  </>;
}
