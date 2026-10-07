import { useEffect, useRef, useState } from 'react';
import type { SegmentVideo } from '../api';

export function useSceneVideoCache(videos: SegmentVideo[]) {
  const cache = useRef(new Map<string, string>());
  const [sources, setSources] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  // Metadata refreshes must not restart downloads when the video files are unchanged.
  const targets = JSON.stringify(videos.map(video => video.url));
  useEffect(() => {
    const urls: string[] = JSON.parse(targets);
    const controller = new AbortController();
    setFailures({});
    const prepare = async () => {
      for (const url of urls) {
        if (cache.current.has(url)) continue;
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`视频读取失败（${response.status}）`);
          const blob = await response.blob();
          if (controller.signal.aborted) return;
          const source = URL.createObjectURL(blob);
          cache.current.set(url, source);
          setSources(previous => ({ ...previous, [url]: source }));
        } catch (error) {
          if (controller.signal.aborted) return;
          setFailures(previous => ({ ...previous, [url]: error instanceof Error ? error.message : String(error) }));
        }
      }
    };
    void prepare();
    return () => controller.abort();
  }, [targets]);
  useEffect(() => () => {
    for (const source of cache.current.values()) URL.revokeObjectURL(source);
    cache.current.clear();
  }, []);
  return {
    sources,
    total: videos.length,
    ready: videos.filter(video => sources[video.url]).length,
    failures: videos.filter(video => failures[video.url]).map(video => failures[video.url]),
  };
}
