import { useEffect, useRef, useState } from 'react';
import type { FileItem } from '../api';
import { latestVideo } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';
import { useRevisionNotesExport } from './RevisionNotes';
import type { NoteScope } from './RevisionNotes';

type Segments = NonNullable<FileItem['segments']>[string];
type Selection = { stage: string; key: string };

export function SceneWorkspace({ scope, segments }: { scope: NoteScope; segments: Segments }) {
  const { scene } = scope;
  const notesExport = useRevisionNotesExport(scope, segments);
  const [segment, setSegment] = useState(segments[0]?.id || '');
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [continuous, setContinuous] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [error, setError] = useState('');
  const stripScroll = useRef<HTMLDivElement>(null);
  const currentSegment = segments.find(item => item.id === segment);
  const latest = currentSegment && latestVideo(currentSegment.videos);
  const chosen = selections[segment] || { stage: latest?.stage || '', key: latest?.key || '' };
  useEffect(() => {
    setSelections(previous => {
      const arriving = segments.filter(item => !previous[item.id] && item.videos.length).map(item => {
        const latest = latestVideo(item.videos)!;
        return [item.id, { stage: latest.stage, key: latest.key }];
      });
      return arriving.length ? { ...previous, ...Object.fromEntries(arriving) } : previous;
    });
  }, [segments]);
  useEffect(() => {
    if (!currentSegment) return;
    const container = stripScroll.current!;
    const button = container.querySelector('[aria-pressed="true"]')!.getBoundingClientRect();
    const bounds = container.getBoundingClientRect();
    container.scrollBy({ left: button.left < bounds.left ? button.left - bounds.left : Math.max(0, button.right - bounds.right) });
  }, [segment]);
  const advance = () => {
    const next = segments[segments.findIndex(item => item.id === segment) + 1];
    if (!continuous || !next) { setAutoPlay(false); return; }
    const selected = selections[next.id];
    const video = selected ? next.videos.find(item => item.stage === selected.stage && item.key === selected.key) : latestVideo(next.videos);
    if (!video) { setAutoPlay(false); setError(`${next.id}尚未选定可播放的画质和版本，连续播放已停在当前分段。`); return; }
    setError('');
    setSegment(next.id);
    setAutoPlay(true);
  };
  return <div className="episode-scene-content" aria-label={scene ? `场次 ${scene} 内容` : '场次内容'}>
    {segments.length > 0 && <div ref={stripScroll} className="segment-scroll"><div className="segment-strip" role="group" aria-label="本场分段" style={{ gridTemplateColumns: segments.map(item => `${item.duration}fr`).join(' '), minWidth: `${segments.reduce((total, item) => total + item.duration, 0) / Math.min(...segments.map(item => item.duration)) * 40}px` }}>
      {segments.map(item => <button key={item.id} aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} title={`${item.id} · 计划时长 ${item.duration}秒`} aria-pressed={item.id === segment} onClick={() => { setAutoPlay(false); setSegment(item.id); setError(''); }}><span>{item.id}</span><span>{item.duration}秒</span></button>)}
    </div></div>}
    {error && <p className="error" role="alert">{error}</p>}
    {currentSegment && <SegmentWorkspace key={segment} scope={scope} segment={segment} items={currentSegment.videos} selection={chosen}
      autoPlay={autoPlay} onVideoError={() => setAutoPlay(false)} onVideoEnded={advance}
      onSelectionChange={value => { setAutoPlay(false); setError(''); setSelections(previous => ({ ...previous, [segment]: value })); }}
      playbackControl={<div className="scene-review-actions"><label className="scene-continuous"><input type="checkbox" checked={continuous} onChange={event => setContinuous(event.target.checked)} />连续播放</label>{notesExport.control}</div>} />}
    {notesExport.dialog}
  </div>;
}
