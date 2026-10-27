import { useQueries } from '@tanstack/react-query';
import type { FileItem } from '../api';
import { latestVideo } from './SegmentVideo';

type DurationEntry = { planned: number; url?: string };
export type ProductionDuration = { seconds: number; estimated: boolean };

export function sceneDurationEntries(episode: FileItem, scene: string, number?: number): DurationEntry[] {
  const segments = episode.segments?.[scene] || [];
  const round = episode.sceneRounds?.[scene]?.find(item => item.number === number);
  return (round?.segments || segments.filter(item => !item.historical)).map(entry => {
    const videos = segments.find(item => item.id === entry.id)?.videos || [];
    const video = 'stage' in entry ? videos.find(item => item.stage === entry.stage && item.run === entry.run)
      : latestVideo(videos.filter(item => item.url));
    const final = video?.products?.find(item => item.role === '最终产物');
    return { planned: entry.duration, url: final ? final.url : video?.url };
  });
}

export function sumProductionDuration(entries: DurationEntry[], measured: ReadonlyMap<string, number>): ProductionDuration | null {
  if (!entries.length) return null;
  return entries.reduce<ProductionDuration>((total, entry) => {
    const actual = entry.url ? measured.get(entry.url) : undefined;
    return { seconds: total.seconds + (actual ?? entry.planned), estimated: total.estimated || actual === undefined };
  }, { seconds: 0, estimated: false });
}

export function formatProductionDuration(duration: ProductionDuration | null) {
  if (!duration) return '时长未记录';
  // Sum full precision first, then display tenths; carry 59.96 seconds into the next minute.
  const tenths = Math.round(duration.seconds * 10);
  const minutes = Math.floor(tenths / 600), seconds = (tenths % 600) / 10;
  return `${minutes ? minutes + '分' : ''}${seconds}秒${duration.estimated ? '*' : ''}`;
}

function readVideoDuration(url: string, signal: AbortSignal): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    const cleanup = () => {
      video.onloadedmetadata = null;
      video.onerror = null;
      signal.removeEventListener('abort', abort);
      video.removeAttribute('src');
      video.load();
    };
    const abort = () => { cleanup(); reject(new DOMException('取消读取视频时长', 'AbortError')); };
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      const seconds = video.duration;
      cleanup();
      if (Number.isFinite(seconds) && seconds > 0) resolve(seconds);
      else reject(new Error('视频未提供有效时长'));
    };
    video.onerror = () => { cleanup(); reject(new Error('视频时长读取失败')); };
    signal.addEventListener('abort', abort, { once: true });
    video.src = url;
  });
}

export function useEpisodeDurations(entries: Record<string, DurationEntry[]>) {
  const urls = [...new Set(Object.values(entries).flatMap(items => items.flatMap(item => item.url ? [item.url] : [])))];
  const queries = useQueries({ queries: urls.map(url => ({
    queryKey: ['video-duration', url], queryFn: ({ signal }: { signal: AbortSignal }) => readVideoDuration(url, signal),
    staleTime: Infinity, retry: false,
  })) });
  const measured = new Map(urls.flatMap((url, index) => queries[index].data === undefined ? [] : [[url, queries[index].data!] as const]));
  const scenes = Object.fromEntries(Object.entries(entries).map(([scene, items]) => [scene, sumProductionDuration(items, measured)]));
  const values = Object.values(scenes);
  const total = values.length && values.every(item => item !== null)
    ? values.reduce<ProductionDuration>((sum, item) => ({ seconds: sum.seconds + item!.seconds, estimated: sum.estimated || item!.estimated }), { seconds: 0, estimated: false }) : null;
  const failed = queries.filter(query => query.isError);
  return { scenes, total, failed: failed.length, retry: () => { for (const query of failed) void query.refetch(); } };
}
