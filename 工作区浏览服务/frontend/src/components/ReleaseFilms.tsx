import { useMemo, useState } from 'react';
import type { FileItem } from '../api';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { UnderlineTabs } from './UnderlineTabs';
import { FloatingMessage } from './Notifications';
import { DownloadButton } from './DownloadButton';
import './ReleaseFilms.css';

const releaseOrder = new Map([['片头', 0], ['片尾', 1]]);
const releaseCategories = ['片头', '片尾', '成片'];

export function releaseVideos(items: FileItem[]): FileItem[] {
  return items.flatMap(item => item.children || item.files ? releaseVideos(item.children || item.files!) : item.kind === 'video' ? [item] : [])
    .sort((a, b) => (releaseOrder.get(a.name.replace(/\.[^.]+$/, '')) ?? 2)
      - (releaseOrder.get(b.name.replace(/\.[^.]+$/, '')) ?? 2)
      || (a.key || a.name).localeCompare(b.key || b.name, 'zh-CN', { numeric: true }));
}

export function ReleaseFilms({ items, active = true }: { items: FileItem[]; active?: boolean }) {
  const categories = useMemo(() => {
    const groups = releaseCategories.map(name => {
      const folder = items.find(item => item.name === name && (item.children || item.files));
      return { value: name, label: name, videos: releaseVideos(folder?.children || folder?.files || []) };
    });
    const unclassified = releaseVideos(items.filter(item => !releaseCategories.includes(item.name) || !(item.children || item.files)));
    if (unclassified.length) groups.push({ value: '未分类', label: '未分类', videos: unclassified });
    return groups;
  }, [items]);
  const [category, setCategory] = useState('片头');
  const current = categories.find(item => item.value === category) || categories[0];
  if (!active) return null;
  return <div className="release-films">
    <UnderlineTabs label="发布成片分类" items={categories} selected={current.value} onChange={setCategory} />
    <ReleaseFilmList key={current.value} videos={current.videos} category={current.label} />
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
        <TabNav scrollable label="发布成片选集" items={videos.slice((page - 1) * 5, page * 5).map(item => ({ value: item.key || item.url!, label: item.name.replace(/\.[^.]+$/, '') }))} selected={current?.key || current?.url || ''} onChange={setSelected} />
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
