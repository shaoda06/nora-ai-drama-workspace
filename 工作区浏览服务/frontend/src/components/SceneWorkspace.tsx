import { useEffect, useRef, useState } from 'react';
import type { FileItem, SegmentVideo as VideoItem } from '../api';
import { latestVideo } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';

type Segments = NonNullable<FileItem['segments']>[string];
type Playlist = { entries: { segment: string; video: VideoItem }[]; index: number; active: boolean; session: number };

export function SceneWorkspace({ scene, segments }: { scene: string; segments: Segments }) {
  const [segment, setSegment] = useState(segments[0]?.id || '');
  const [selection, setSelection] = useState<{ stage: string; key: string } | null>(null);
  const [playlist, setPlaylist] = useState<Playlist | null>(null);
  const [error, setError] = useState('');
  const stripScroll = useRef<HTMLDivElement>(null);
  const playing = playlist?.entries[playlist.index];
  const selectedSegment = playing?.segment || segment;
  const currentSegment = segments.find(item => item.id === selectedSegment);
  const latest = currentSegment && latestVideo(currentSegment.videos);
  const chosen = playing ? { stage: playing.video.stage, key: playing.video.key } : selection || { stage: latest?.stage || '', key: latest?.key || '' };
  useEffect(() => {
    if (!currentSegment) return;
    const container = stripScroll.current!;
    const button = container.querySelector('[aria-pressed="true"]')!.getBoundingClientRect();
    const bounds = container.getBoundingClientRect();
    container.scrollBy({ left: button.left < bounds.left ? button.left - bounds.left : Math.max(0, button.right - bounds.right) });
  }, [selectedSegment]);
  const stop = () => setPlaylist(previous => previous && { ...previous, active: false });
  const start = () => {
    if (playlist?.active) { stop(); return; }
    const entries = segments.map(item => ({ segment: item.id, video: latestVideo(item.videos) }));
    const missing = entries.filter(item => !item.video);
    if (missing.length) { setError(`${missing.map(item => item.segment).join('、')}尚无视频，无法连续播放完整场次。`); return; }
    setError('');
    setSelection(null);
    setPlaylist({ entries: entries.map(item => ({ segment: item.segment, video: item.video! })), index: 0, active: true, session: (playlist?.session || 0) + 1 });
  };
  return <div className="episode-scene-content" aria-label={scene ? `场次 ${scene} 内容` : '场次内容'}>
    {segments.length > 0 && <div ref={stripScroll} className="segment-scroll"><div className="segment-strip" role="group" aria-label="本场分段" style={{ gridTemplateColumns: segments.map(item => `${item.duration}fr`).join(' '), minWidth: `${segments.reduce((total, item) => total + item.duration, 0) / Math.min(...segments.map(item => item.duration)) * 40}px` }}>
      {segments.map(item => <button key={item.id} aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} title={`${item.id} · 计划时长 ${item.duration}秒`} aria-pressed={item.id === selectedSegment} onClick={() => { setPlaylist(null); setSelection(null); setSegment(item.id); setError(''); }}><span>{item.id}</span><span>{item.duration}秒</span></button>)}
    </div></div>}
    {error && <p className="error" role="alert">{error}</p>}
    {currentSegment && <SegmentWorkspace key={selectedSegment} items={currentSegment.videos} selection={chosen}
      autoPlay={playlist?.active || false} playbackSession={playlist?.session || 0} onVideoError={stop}
      onVideoEnded={() => setPlaylist(previous => previous && previous.active ? (previous.index + 1 < previous.entries.length
        ? { ...previous, index: previous.index + 1 } : { ...previous, active: false }) : previous)}
      onSelectionChange={value => { setSegment(selectedSegment); setPlaylist(null); setSelection(value); }}
      playbackControl={<button className="scene-play-button" aria-pressed={playlist?.active || false} onClick={start}>{playlist?.active ? '停止连续播放' : '连续播放'}</button>} />}
  </div>;
}
