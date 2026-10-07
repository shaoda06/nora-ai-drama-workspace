import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { hasUnsavedNotes } from './revisionNotes';
import { saveRefreshPosition } from './refreshPosition';

declare const __APP_VERSION__: string;
export const APP_VERSION = __APP_VERSION__;
interface Service { version: string; ready: boolean; environment: string }

function canRefresh() {
  const editing = document.activeElement?.matches('input:not([type="checkbox"]):not([type="radio"]):not([type="range"]), textarea, [contenteditable="true"]');
  const playing = [...document.querySelectorAll<HTMLMediaElement>('video, audio')].some(media => !media.paused && !media.ended);
  return !editing && !playing && !document.querySelector('dialog[open]') && !hasUnsavedNotes();
}

export function useAppUpdate() {
  const service = useQuery({ queryKey: ['service'], queryFn: () => get<Service>('/api/service'),
    refetchInterval: 15000, refetchOnWindowFocus: true });
  const pending = !service.isError && service.data?.ready === true && service.data.version !== APP_VERSION;
  const { refetch } = service;
  useEffect(() => {
    if (!pending) return;
    let checking = false;
    let disposed = false;
    const check = async () => {
      if (checking || !canRefresh()) return;
      checking = true;
      const result = await refetch();
      if (!disposed && !result.isError && result.data?.ready && result.data.version !== APP_VERSION && canRefresh()) {
        saveRefreshPosition();
        window.location.reload();
      }
      checking = false;
    };
    const timer = window.setInterval(() => { void check(); }, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [pending, refetch]);
  return { service, pending };
}
