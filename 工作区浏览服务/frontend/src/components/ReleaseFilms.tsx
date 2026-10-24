import { useMemo, useState } from 'react';
import type { FileItem } from '../api';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { FloatingMessage } from './Notifications';
import './ReleaseFilms.css';

export function ReleaseFilms({ items, active = true }: { items: FileItem[]; active?: boolean }) {
  const videos = useMemo(() => {
    const collect = (entries: FileItem[]): FileItem[] => entries.flatMap(item =>
      item.children || item.files ? collect(item.children || item.files!) : item.kind === 'video' ? [item] : []);
    return collect(items).sort((a, b) => (a.key || a.name).localeCompare(b.key || b.name, 'zh-CN', { numeric: true }));
  }, [items]);
  const [selected, setSelected] = useState('');
  const index = Math.max(0, videos.findIndex(item => (item.key || item.url) === selected));
  const page = Math.floor(index / 5) + 1;
  const current = videos[index];
  if (!active) return null;
  return <div className="release-films">
    <div className="release-films-selector">
      <TabNav label="发布成片选集" items={videos.slice((page - 1) * 5, page * 5).map(item => ({ value: item.key || item.url!, label: item.name.replace(/\.[^.]+$/, '') }))} selected={current?.key || current?.url || ''} onChange={setSelected} />
      <Pagination alwaysShow itemLabel="集" pageSize={5} page={page} total={videos.length} change={page => setSelected(videos[(page - 1) * 5].key || videos[(page - 1) * 5].url!)} />
    </div>
    {current ? <ReleaseFilmPlayer key={current.key || current.url} item={current} /> : <p className="muted">暂无发布成片视频。</p>}
  </div>;
}

function ReleaseFilmPlayer({ item }: { item: FileItem }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  return <>
    <video key={attempt} className="release-films-player" aria-label={item.name} controls preload="metadata" src={item.url} onError={() => setFailed(true)} />
    {failed && <FloatingMessage tone="error">{item.name} 无法播放。<button onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>重新加载视频</button></FloatingMessage>}
  </>;
}
