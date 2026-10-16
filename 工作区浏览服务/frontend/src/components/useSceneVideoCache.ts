import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { SegmentVideo } from '../api';

export function useSceneVideoCache(videos: SegmentVideo[], priorityUrls: string[]) {
  const cache = useRef(new Map<string, string>());
  const requests = useRef(new Map<string, AbortController>());
  const wanted = useRef<string[]>([]);
  const usedSources = useRef(new Set<string>());
  const failed = useRef(new Set<string>());
  const active = useRef(false);
  const priority = useRef(priorityUrls);
  priority.current = priorityUrls;
  const [sources, setSources] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const releaseUnused = useCallback(() => {
    let changed = false;
    for (const [url, source] of cache.current) {
      if (wanted.current.includes(url) || usedSources.current.has(source)) continue;
      URL.revokeObjectURL(source);
      cache.current.delete(url);
      changed = true;
    }
    if (changed && active.current) setSources(Object.fromEntries(cache.current));
  }, []);
  const retainSource = useCallback((source: string) => {
    usedSources.current.add(source);
    return () => { usedSources.current.delete(source); releaseUnused(); };
  }, [releaseUnused]);
  const prepare = useCallback(function pump() {
    if (!active.current) return;
    while (requests.current.size < 2) {
      const pending = wanted.current.filter(url => !cache.current.has(url) && !requests.current.has(url) && !failed.current.has(url));
      const url = priority.current.find(url => pending.includes(url)) || pending[0];
      if (!url) return;
      const controller = new AbortController();
      requests.current.set(url, controller);
      void (async () => {
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`视频读取失败（${response.status}）`);
          const blob = await response.blob();
          if (controller.signal.aborted || !active.current) return;
          const source = URL.createObjectURL(blob);
          cache.current.set(url, source);
          setSources(previous => ({ ...previous, [url]: source }));
        } catch (error) {
          if (controller.signal.aborted || !active.current) return;
          failed.current.add(url);
          setFailures(previous => ({ ...previous, [url]: error instanceof Error ? error.message : String(error) }));
        } finally {
          if (requests.current.get(url) === controller) {
            requests.current.delete(url);
            window.setTimeout(pump, 0);
          }
        }
      })();
    }
  }, []);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      for (const controller of requests.current.values()) controller.abort();
      requests.current.clear();
      for (const source of cache.current.values()) URL.revokeObjectURL(source);
      cache.current.clear();
    };
  }, []);
  // Metadata refreshes and priority changes must not restart unchanged downloads.
  const targets = JSON.stringify(videos.map(video => video.url));
  useEffect(() => {
    wanted.current = JSON.parse(targets);
    failed.current.clear();
    setFailures({});
    for (const [url, controller] of requests.current) {
      if (!wanted.current.includes(url)) controller.abort();
    }
    releaseUnused();
    // Let the player's metadata request start before fetching the same cache key.
    const start = window.setTimeout(prepare, 0);
    return () => window.clearTimeout(start);
  }, [targets, prepare, releaseUnused]);
  return {
    sources,
    retainSource,
    total: videos.length,
    ready: videos.filter(video => sources[video.url]).length,
    failures: videos.filter(video => failures[video.url]).map(video => failures[video.url]),
  };
}
