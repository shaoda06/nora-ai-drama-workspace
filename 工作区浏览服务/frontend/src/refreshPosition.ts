import { useCallback, useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';

const STORAGE_KEY = 'nora-auto-refresh-position';
interface Position { href: string; scrollY: number; values: Record<string, unknown> }
const stored = sessionStorage.getItem(STORAGE_KEY);
const restored: Position | null = stored ? JSON.parse(stored) : null;
sessionStorage.removeItem(STORAGE_KEY);
const previous = restored?.href === window.location.href ? restored : null;
const values: Record<string, unknown> = {};

// Reloads restore these choices; navigation within the app keeps its existing defaults.
export function useRefreshState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [entry, setEntry] = useState(() => ({ key, value: (previous?.values[key] as T | undefined) ?? initial }));
  if (entry.key !== key) setEntry({ key, value: (previous?.values[key] as T | undefined) ?? initial });
  useEffect(() => {
    values[key] = entry.value;
    if (previous) delete previous.values[key];
  }, [key, entry.value]);
  useEffect(() => () => { delete values[key]; }, [key]);
  const setValue = useCallback<Dispatch<SetStateAction<T>>>(next => {
    setEntry(current => {
      const value = typeof next === 'function' ? (next as (value: T) => T)(current.value) : next;
      return current.key === key && Object.is(current.value, value) ? current : { key, value };
    });
  }, [key]);
  return [entry.value, setValue];
}

export function saveRefreshPosition() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ href: window.location.href, scrollY: window.scrollY, values }));
}

window.addEventListener('pagehide', saveRefreshPosition);

export function restoreRefreshScroll(container: HTMLElement) {
  if (!previous || previous.href !== window.location.href) return;
  const observer = new ResizeObserver(() => {
    window.scrollTo(0, previous.scrollY);
    if (document.documentElement.scrollHeight >= previous.scrollY + window.innerHeight) observer.disconnect();
  });
  observer.observe(container);
  const stop = () => observer.disconnect();
  window.addEventListener('wheel', stop, { once: true, passive: true });
  window.addEventListener('touchstart', stop, { once: true, passive: true });
  return () => {
    observer.disconnect();
    window.removeEventListener('wheel', stop);
    window.removeEventListener('touchstart', stop);
  };
}
