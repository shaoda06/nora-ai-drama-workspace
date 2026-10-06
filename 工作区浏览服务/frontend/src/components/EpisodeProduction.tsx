import { useEffect, useRef, useState } from 'react';
import type { FileItem } from '../api';
import { Original, Rich } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';

export function EpisodeProduction({ items, selected, onSelect }: { items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void }) {
  const [scene, setScene] = useState('');
  const [page, setPage] = useState(1);
  const [segment, setSegment] = useState('');
  const cards = useRef<HTMLDivElement>(null);
  const previousEpisode = useRef(selected);
  useEffect(() => {
    if (!selected && previousEpisode.current) cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${previousEpisode.current}"]`)!.focus();
    previousEpisode.current = selected;
  }, [selected]);
  const current = items.find(item => item.name === selected);
  const scenes = current?.scenes || [];
  const selectedScene = scene || scenes[0] || '';
  const segments = current?.segments?.[selectedScene] || [];
  const selectedSegment = segment || segments[0]?.id || '';
  const selectedScript = segments.find(item => item.id === selectedSegment);
  const open = (name: string) => {
    setScene('');
    setSegment('');
    onSelect(name);
  };
  return current ? <div className="episode-detail">
    {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={id => { setScene(id); setSegment(''); }} />}
    <div className="episode-scene-content" aria-label={selectedScene ? `场次 ${selectedScene} 内容` : '场次内容'}>
      {segments.length > 0 && <div className="segment-scroll"><div className="segment-strip" role="group" aria-label="本场分段" style={{ gridTemplateColumns: segments.map(item => `${item.duration}fr`).join(' '), minWidth: `${segments.reduce((total, item) => total + item.duration, 0) / Math.min(...segments.map(item => item.duration)) * 40}px` }}>
        {segments.map(item => <button key={item.id} aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} title={`${item.id} · 计划时长 ${item.duration}秒`} aria-pressed={item.id === selectedSegment} onClick={() => setSegment(item.id)}><span>{item.id}</span><span>{item.duration}秒</span></button>)}
      </div></div>}
      {selectedSegment && <div className="segment-workspace" key={selectedScene + '/' + selectedSegment}>
        <div className="video-placeholder" role="region" aria-label="视频区域" />
        <section className="segment-script" aria-label={`分段 ${selectedSegment} 分镜脚本`}>
          {selectedScript?.scriptUrl && <div className="segment-script-actions"><Original url={selectedScript.scriptUrl} label="查看原文件" /></div>}
          {selectedScript?.scriptHtml ? <Rich html={selectedScript.scriptHtml} /> : <p className="muted">本段分镜正文尚未记录。</p>}
        </section>
      </div>}
    </div>
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
