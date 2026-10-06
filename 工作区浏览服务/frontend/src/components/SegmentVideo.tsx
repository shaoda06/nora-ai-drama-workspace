import { useState } from 'react';
import type { SegmentVideo as VideoItem } from '../api';
import { Original } from '../components';
import { TabNav } from './TabNav';

export function SegmentVideo({ items }: { items: VideoItem[] }) {
  const [selected, setSelected] = useState('');
  const [error, setError] = useState(false);
  const current = items.find(item => item.key === selected) || items[0];
  return <section className="segment-video" aria-label="视频区域">
    {items.length > 0 && <div className="video-tabs"><TabNav label="视频版本" items={items.map(item => ({ value: item.key, label: item.name }))} selected={current.key} onChange={key => { setSelected(key); setError(false); }} /></div>}
    {current ? <>
      <video key={current.key} controls preload="metadata" src={current.url} aria-label={`${current.name} ${current.run} ${current.stage}`} onError={() => setError(true)} />
      <div className="video-source"><span>{current.run} · {current.stage}</span><Original url={current.url} label="查看视频原文件" /></div>
      {error && <p className="error" role="alert">视频无法播放，请打开原文件。</p>}
    </> : <div className="video-placeholder" />}
  </section>;
}
