import { useEffect, useRef, useState } from 'react';
import type { SegmentVideo as VideoItem } from '../api';
import { Original } from '../components';

export const candidateLabel = (number: number) => {
  const digits = '零一二三四五六七八九';
  return '候选' + (number < 10 ? digits[number] : number < 100
    ? (number < 20 ? '' : digits[Math.floor(number / 10)]) + '十' + (number % 10 ? digits[number % 10] : '') : number);
};

export const latestVideo = (items: VideoItem[]) => items.reduce<VideoItem | undefined>((latest, item) => !latest || Number(item.run.slice(1)) > Number(latest.run.slice(1)) ? item : latest, undefined);

export function SegmentVideo({ current, onTimeChange, scene = false, autoPlay = false, syncTime, onPlay, onEnded, onError }: {
  current?: VideoItem; onTimeChange: (time: number) => void; scene?: boolean; autoPlay?: boolean; syncTime?: number;
  onPlay?: () => void; onEnded?: () => void; onError?: () => void;
}) {
  const [error, setError] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (scene && !autoPlay) video.current?.pause();
  }, [scene, autoPlay]);
  useEffect(() => {
    if (syncTime !== undefined && video.current!.readyState >= 1) video.current!.currentTime = syncTime;
  }, [syncTime]);
  const label = (item: VideoItem) => item.approved ? '正式版' : candidateLabel(item.candidateNumber);
  return <section className={scene ? 'segment-video scene-video' : 'segment-video'} aria-label={scene ? '场次视频区域' : '视频区域'}>
    {current ? <video ref={video} key={current.key} controls autoPlay={autoPlay} preload="metadata" src={current.url} aria-label={`${label(current)} ${current.run} ${current.stage}`} onError={() => { setError(true); onError?.(); }} onPlay={onPlay}
      onLoadedMetadata={event => { if (syncTime !== undefined) event.currentTarget.currentTime = syncTime; onTimeChange(event.currentTarget.currentTime); }}
      onTimeUpdate={event => onTimeChange(event.currentTarget.currentTime)}
      onSeeked={event => onTimeChange(event.currentTarget.currentTime)}
      onPause={event => onTimeChange(event.currentTarget.currentTime)}
      onEnded={event => { onTimeChange(event.currentTarget.currentTime); onEnded?.(); }} /> : <div className="video-placeholder">视频区域</div>}
    <div className="video-source">{current && <><span>{current.approved ? '正式版 · 原' : ''}{candidateLabel(current.candidateNumber)} · {current.run} · {current.stage}</span><Original url={current.url} label="查看视频原文件" /></>}</div>
    {error && <p className="error" role="alert">视频无法播放，请打开原文件。</p>}
  </section>;
}
