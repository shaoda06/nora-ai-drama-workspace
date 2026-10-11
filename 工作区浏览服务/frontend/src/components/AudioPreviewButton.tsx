import { PointerTooltip } from './PointerTooltip';
import { useEffect, useRef, useState } from 'react';
import { useNotify } from './Notifications';

export function useAudioPreview(active: boolean, selection: string | null, revision: number) {
  const audio = useRef<HTMLAudioElement>(null);
  const currentId = useRef<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const notify = useNotify();
  useEffect(() => {
    audio.current?.pause();
    return () => { audio.current?.pause(); };
  }, [active, selection]);
  const toggle = (id: string, url: string) => {
    const player = audio.current!;
    if (currentId.current === id && !player.paused) { player.pause(); return; }
    player.pause();
    if (currentId.current !== id || player.ended) {
      currentId.current = id;
      setProgress(0);
      player.src = url + `?v=${revision}`;
    }
    void player.play().catch(error => {
      if (error.name !== 'AbortError') notify('音频播放失败，请稍后重试。', 'error');
    });
  };
  const player = <audio ref={audio} preload="none" onPlay={() => setPlayingId(currentId.current)} onPause={() => setPlayingId(null)} onTimeUpdate={event => {
    const player = event.currentTarget;
    if (player.duration > 0) setProgress(player.currentTime / player.duration);
  }} onEnded={() => { setPlayingId(null); setProgress(0); }} />;
  return { player, toggle, playingId, currentId: currentId.current, progress };
}

export function AudioPreviewButton({ name, enabled, playing, progress, onClick }: {
  name: string; enabled: boolean; playing: boolean; progress: number; onClick: () => void;
}) {
  return <PointerTooltip text={!enabled ? '暂无参考音频' : playing ? '暂停音频' : '试听音频'}><button className="voice-preview" disabled={!enabled} aria-label={!enabled ? `${name}暂无音频` : `${playing ? '暂停' : '播放'}${name}`}  aria-pressed={playing} onClick={onClick}>
    {playing ? 'Ⅱ' : '▶'}<svg className="voice-progress" viewBox="0 0 28 28" aria-hidden="true"><rect x="1" y="1" width="26" height="26" rx="6" pathLength="100" strokeDasharray="100" strokeDashoffset={100 * (1 - progress)} /></svg>
  </button></PointerTooltip>;
}
