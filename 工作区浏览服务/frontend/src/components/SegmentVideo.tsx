import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode, Ref } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { TaskDetailDialog } from './TaskDetailDialog';
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

export function missingVideoState(current?: VideoItem, recordedKey = '') {
  // A planned revision has a key too; only a saved media identity or a
  // successful generation/collection record establishes an existing output.
  const unavailable = !!current?.fileRevision || current?.taskStatus === '成功'
    || !!current?.deliveryStatus.includes('已取回') || /\.(mp4|webm|mov)$/.test(recordedKey);
  const recorded = current?.taskStatus?.split(/[；;]/)[0];
  const status: Record<string, string> = { 已准备: '等待提交', 等待提交: '等待提交', 排队中: '排队中',
    已提交: '任务已提交', 运行中: '正在生成中', 正在生成: '正在生成中', 生成中: '正在生成中',
    取回中: '正在取回视频', 失败: '生成失败，请查看任务详情', 已取消: '任务已取消', 暂停中: '任务已暂停' };
  return { unavailable, message: unavailable ? '已有视频不可播放，请检查视频文件及取回记录。'
    : status[recorded || ''] || '尚未生成视频' };
}

export interface VideoTaskState { id: string; status: string; updated_at: string }

export const videoTaskMessages: Record<string, string> = {
  local_queued: '排队中', preparing: '准备提交中', submitting: '正在提交任务', queued: '任务已提交',
  running: '正在生成中', collecting: '正在取回视频', completed: '生成已完成', paused: '任务已暂停',
  failed: '生成失败，请查看任务详情', rejected: '提交失败，请查看任务详情',
  collection_failed: '视频取回失败，请查看任务详情', cancelled: '任务已取消', resolved: '任务已结案',
  needs_attention: '任务状态待核对', submission_unknown: '提交结果待核对',
};

// A media clock can keep advancing after the browser loses its video renderer.
// loadedmetadata and error alone do not report that state.
export function watchVideoPlayback(element: HTMLVideoElement, recover: () => void) {
  let stopped = false;
  let frameRequest: number | undefined;
  let lastFrame = performance.now();
  let previousTime = element.currentTime;
  let previousFrames = element.getVideoPlaybackQuality?.().totalVideoFrames;
  let waitingSince: number | undefined;
  const reset = () => { lastFrame = performance.now(); previousTime = element.currentTime; waitingSince = undefined; };
  const interrupted = () => { waitingSince ??= performance.now(); };
  const frame = () => {
    if (stopped) return;
    lastFrame = performance.now();
    frameRequest = element.requestVideoFrameCallback(frame);
  };
  if (typeof element.requestVideoFrameCallback === 'function') frameRequest = element.requestVideoFrameCallback(frame);
  element.addEventListener('playing', reset);
  element.addEventListener('seeked', reset);
  element.addEventListener('waiting', interrupted);
  element.addEventListener('stalled', interrupted);
  element.addEventListener('error', interrupted);
  const timer = window.setInterval(() => {
    if (stopped) return;
    const now = performance.now();
    if (document.hidden) { reset(); return; }
    const frames = element.getVideoPlaybackQuality?.().totalVideoFrames;
    if (frameRequest === undefined && frames !== undefined && frames !== previousFrames) { previousFrames = frames; lastFrame = now; }
    const movingWithoutFrames = !element.paused && !element.ended && element.currentTime > previousTime
      && (frameRequest !== undefined || frames !== undefined) && now - lastFrame >= 3000;
    const stalled = waitingSince !== undefined && now - waitingSince >= 3000
      && (!!element.error || (!element.paused && element.readyState < 3));
    previousTime = element.currentTime;
    if (!movingWithoutFrames && !stalled) return;
    stopped = true;
    recover();
  }, 1000);
  if (element.error) interrupted();
  return () => {
    stopped = true;
    window.clearInterval(timer);
    if (frameRequest !== undefined) element.cancelVideoFrameCallback(frameRequest);
    element.removeEventListener('playing', reset);
    element.removeEventListener('seeked', reset);
    element.removeEventListener('waiting', interrupted);
    element.removeEventListener('stalled', interrupted);
    element.removeEventListener('error', interrupted);
  };
}

export interface SegmentVideoHandle { seekTo: (time: number) => void }

export function SegmentVideo({ current, onTimeChange, autoPlay = false, onEnded, onError, onFileRevision, cachedSource, retainSource, wide, onToggleWide, continuousControl, selectorControl, playerRef }: {
  current?: VideoItem; onTimeChange: (time: number) => void; autoPlay?: boolean;
  onEnded?: () => void; onError?: () => void;
  onFileRevision?: (revision: string) => void;
  cachedSource?: string; wide: boolean; onToggleWide: () => void; continuousControl: ReactNode; selectorControl?: ReactNode;
  retainSource: (source: string) => () => void;
  playerRef: Ref<SegmentVideoHandle>;
}) {
  const [error, setError] = useState(false);
  const [detailId, setDetailId] = useState('');
  const queryClient = useQueryClient();
  const task = useQuery<VideoTaskState>({
    queryKey: ['video-task', current?.taskStateUrl],
    queryFn: async ({ signal }) => {
      const response = await fetch(current!.taskStateUrl!, { signal, cache: 'no-store' });
      if (!response.ok) throw new Error('任务状态读取失败');
      return response.json();
    },
    enabled: !!current?.taskStateUrl && !current.url,
    staleTime: 0, retry: false, refetchInterval: 3000,
    refetchIntervalInBackground: false, refetchOnWindowFocus: 'always',
  });
  useEffect(() => {
    if (task.data?.status === 'completed') void queryClient.invalidateQueries({ queryKey: ['episode'] });
  }, [task.data?.status, task.data?.updated_at, queryClient]);
  const missing = missingVideoState(current);
  const status = current?.taskStateUrl && !current.url
    ? task.isError ? '任务状态暂不可用' : task.data
      ? missing.unavailable && task.data.status === 'completed' ? missing.message
        : videoTaskMessages[task.data.status] || '任务状态待核对'
      : '正在读取任务状态'
    : current?.url ? '视频已生成，请加载新文件' : missing.message;
  const [loaded, setLoaded] = useState(current);
  const [source, setSource] = useState(cachedSource || current?.url);
  useLayoutEffect(() => source ? retainSource(source) : undefined, [source, retainSource]);
  const [playOnLoad, setPlayOnLoad] = useState(autoPlay);
  const video = useRef<HTMLVideoElement>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const [recovering, setRecovering] = useState(false);
  const attempts = useRef(0);
  const restore = useRef<{ volume: number; muted: boolean; playbackRate: number } | null>(null);
  const pendingSeek = useRef<number | null>(null);
  const seekTo = (time: number) => {
    const element = video.current;
    if (!element || !Number.isFinite(time) || time < 0) return;
    if (element.readyState === 0) { pendingSeek.current = time; return; }
    pendingSeek.current = null;
    element.currentTime = Number.isFinite(element.duration) ? Math.min(time, element.duration) : time;
    onTimeChange(element.currentTime);
  };
  const recoverPlayback = () => {
    const element = video.current;
    if (!element) return;
    if (attempts.current >= 2) { setRecovering(false); setError(true); onError?.(); return; }
    attempts.current += 1;
    pendingSeek.current ??= element.currentTime;
    restore.current ??= { volume: element.volume, muted: element.muted, playbackRate: element.playbackRate };
    setPlayOnLoad(!element.paused && !element.ended);
    setError(false);
    setRecovering(true);
    setReloadCount(value => value + 1);
  };
  useEffect(() => {
    if (video.current) return watchVideoPlayback(video.current, recoverPlayback);
  }, [source, loaded?.fileRevision, reloadCount]);
  useImperativeHandle(playerRef, () => ({ seekTo }));
  const updated = current && loaded && current.fileRevision !== loaded.fileRevision;
  useEffect(() => {
    if (!autoPlay) video.current?.pause();
  }, [autoPlay]);
  const description = current && `${current.stage} · ${current.run} · ${candidateLabel(current.candidateNumber)}${current.approved ? '（正式版）' : ''}`;
  return <section className="segment-video" aria-label="视频区域">
    {loaded?.url ? <video ref={video} key={`${loaded.fileRevision}:${reloadCount}`} controls autoPlay={playOnLoad} preload="metadata" src={source} aria-label={description}
      onLoadedMetadata={event => { if (restore.current) { Object.assign(event.currentTarget, restore.current); restore.current = null; } if (pendingSeek.current !== null) seekTo(pendingSeek.current); else onTimeChange(event.currentTarget.currentTime); onFileRevision?.(loaded.fileRevision); }}
      onLoadedData={() => setRecovering(false)}
      onTimeUpdate={event => onTimeChange(event.currentTarget.currentTime)}
      onSeeked={event => onTimeChange(event.currentTarget.currentTime)}
      onPause={event => onTimeChange(event.currentTarget.currentTime)}
      onEnded={event => { onTimeChange(event.currentTarget.currentTime); onEnded?.(); }} /> : <div className="video-placeholder video-task-placeholder"><span role="status">{current ? status : '尚未生成视频'}</span>
      {current?.taskStateUrl && task.data && <button onClick={() => setDetailId(task.data.id)}>查看任务详情</button>}</div>}
    <div className="video-source">
      <div className="video-source-summary">{selectorControl}{current && loaded && <span>{description}</span>}</div>
      <div className="video-source-actions">
        {continuousControl}
        <button className="video-layout-toggle" aria-pressed={wide} onClick={onToggleWide}>{wide ? '恢复布局' : '宽屏显示'}</button>
        {loaded?.url && <Original url={loaded.url} label="查看视频原文件" />}
      </div>
    </div>
    {updated && <div className="video-update" role="status"><span>视频已有更新</span><button onClick={() => { setPlayOnLoad(video.current ? !video.current.paused : false); setLoaded(current); setSource(cachedSource || current.url); attempts.current = 0; pendingSeek.current = null; restore.current = null; setRecovering(false); setError(false); onTimeChange(0); onFileRevision?.(current.fileRevision); }}>加载新文件</button></div>}
    {detailId && <TaskDetailDialog id={detailId} updatedAt={task.data?.updated_at} nodes={[]} close={() => setDetailId('')} openTask={setDetailId} />}
    {recovering && <p role="status">正在恢复视频画面…</p>}
    {error && <p className="error" role="alert">视频画面恢复失败。<button onClick={() => { attempts.current = 0; recoverPlayback(); }}>重新加载视频</button>，也可打开原文件检查。</p>}
  </section>;
}
