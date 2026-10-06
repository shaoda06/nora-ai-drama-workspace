import { useEffect, useRef, useState } from 'react';
import type { FileItem } from '../api';
import { Rich } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';

export function EpisodeProduction({ items, selected, onSelect }: { items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void }) {
  const [scene, setScene] = useState('');
  const [page, setPage] = useState(1);
  const heading = useRef<HTMLHeadingElement>(null);
  const cards = useRef<HTMLDivElement>(null);
  const previousEpisode = useRef(selected);
  useEffect(() => {
    if (!selected && previousEpisode.current) cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${previousEpisode.current}"]`)!.focus();
    previousEpisode.current = selected;
  }, [selected]);
  const current = items.find(item => item.name === selected);
  const scenes = current?.scenes || [];
  const selectedScene = scene || scenes[0] || '';
  const open = (name: string) => {
    setScene('');
    onSelect(name);
    requestAnimationFrame(() => { heading.current!.scrollIntoView({ block: 'start' }); heading.current!.focus({ preventScroll: true }); });
  };
  return current ? <div className="episode-detail">
    <div className="episode-heading">
      <h3 ref={heading} tabIndex={-1}>{current.name} · {current.title || '题名未记录'}</h3>
      <Rich html={current.statusHtml} />
      <button onClick={() => onSelect(null)}>← 返回选集列表</button>
    </div>
    {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={setScene} />}
    <div className="episode-scene-content" aria-label={selectedScene ? `场次 ${selectedScene} 内容` : '场次内容'} />
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
