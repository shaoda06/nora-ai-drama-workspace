import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { SegmentVideo as VideoItem } from '../api';
import { Original } from '../components';

export const candidateLabel = (number: number) => {
  const digits = '零一二三四五六七八九';
  return '候选' + (number < 10 ? digits[number] : number < 100
    ? (number < 20 ? '' : digits[Math.floor(number / 10)]) + '十' + (number % 10 ? digits[number % 10] : '') : number);
};

export const latestVideo = (items: VideoItem[]) => {
  const stages = ['一采', '二采', '后处理'];
  return items.reduce<VideoItem | undefined>((latest, item) => {
    if (!latest) return item;
    const stage = stages.indexOf(item.stage) - stages.indexOf(latest.stage);
    const revision = Number(item.run.slice(1)) - Number(latest.run.slice(1));
    return stage > 0 || (stage === 0 && revision > 0) ? item : latest;
  }, undefined);
};

export const selectedRevision = (items: VideoItem[], selection: { stage: string; key: string }) => {
  const identity = (key: string) => key.split('/').pop()?.replace(/\.(mp4|webm|mov)$/, '');
  return items.find(item => item.stage === selection.stage && item.key === selection.key)
    || items.find(item => item.stage === selection.stage && identity(item.key) === identity(selection.key));
};

export function SegmentVideo({ current, onTimeChange, autoPlay = false, onEnded, onError, onFileRevision, cachedSource, wide, onToggleWide, continuousControl, selectorControl }: {
  current?: VideoItem; onTimeChange: (time: number) => void; autoPlay?: boolean;
  onEnded?: () => void; onError?: () => void;
  onFileRevision?: (revision: string) => void;
  cachedSource?: string; wide: boolean; onToggleWide: () => void; continuousControl: ReactNode; selectorControl?: ReactNode;
}) {
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(current);
  const [source, setSource] = useState(cachedSource || current?.url);
  const [playOnLoad, setPlayOnLoad] = useState(autoPlay);
  const video = useRef<HTMLVideoElement>(null);
  const updated = current && loaded && current.fileRevision !== loaded.fileRevision;
  useEffect(() => {
    if (!autoPlay) video.current?.pause();
  }, [autoPlay]);
  const label = (item: VideoItem) => item.approved ? '正式版' : candidateLabel(item.candidateNumber);
  return <section className="segment-video" aria-label="视频区域">
    {loaded?.url ? <video ref={video} key={loaded.fileRevision} controls autoPlay={playOnLoad} preload="metadata" src={source} aria-label={`${label(current!)} ${current!.run} ${current!.stage}`} onError={() => { setError(true); onError?.(); }}
      onLoadedMetadata={event => { onTimeChange(event.currentTarget.currentTime); onFileRevision?.(loaded.fileRevision); }}
      onTimeUpdate={event => onTimeChange(event.currentTarget.currentTime)}
      onSeeked={event => onTimeChange(event.currentTarget.currentTime)}
      onPause={event => onTimeChange(event.currentTarget.currentTime)}
      onEnded={event => { onTimeChange(event.currentTarget.currentTime); onEnded?.(); }} /> : <div className="video-placeholder">{current ? `本轮暂无可播放视频${current.taskStatus && current.taskStatus !== '未记录' ? `（${current.taskStatus}）` : ''}；可查看本轮已关联资料。` : '视频区域'}</div>}
    <div className="video-source">
      <div className="video-source-summary">{selectorControl}{current && loaded && <span>{current.approved ? '正式版 · 原' : ''}{candidateLabel(current.candidateNumber)} · {current.run} · {current.stage}</span>}</div>
      <div className="video-source-actions">
        {continuousControl}
        <button className="video-layout-toggle" aria-pressed={wide} onClick={onToggleWide}>{wide ? '恢复布局' : '宽屏显示'}</button>
        {loaded?.url && <Original url={loaded.url} label="查看视频原文件" />}
      </div>
    </div>
    {updated && <div className="video-update" role="status"><span>视频已有更新</span><button onClick={() => { setPlayOnLoad(video.current ? !video.current.paused : false); setLoaded(current); setSource(cachedSource || current.url); setError(false); onTimeChange(0); onFileRevision?.(current.fileRevision); }}>加载新文件</button></div>}
    {error && <p className="error" role="alert">视频无法播放，请打开原文件。</p>}
  </section>;
}
