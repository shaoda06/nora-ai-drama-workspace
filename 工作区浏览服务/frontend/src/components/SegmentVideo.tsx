import { useState } from 'react';
import type { SegmentVideo as VideoItem } from '../api';
import { Original } from '../components';

export const candidateLabel = (number: number) => {
  const digits = '零一二三四五六七八九';
  return '候选' + (number < 10 ? digits[number] : number < 100
    ? (number < 20 ? '' : digits[Math.floor(number / 10)]) + '十' + (number % 10 ? digits[number % 10] : '') : number);
};

export function SegmentVideo({ current }: { current?: VideoItem }) {
  const [error, setError] = useState(false);
  const label = (item: VideoItem) => item.approved ? '正式版' : candidateLabel(item.candidateNumber);
  return <section className="segment-video" aria-label="视频区域">
    {current ? <>
      <video key={current.key} controls preload="metadata" src={current.url} aria-label={`${label(current)} ${current.run} ${current.stage}`} onError={() => setError(true)} />
      <div className="video-source"><span>{current.approved ? '正式版 · 原' : ''}{candidateLabel(current.candidateNumber)} · {current.run} · {current.stage}</span><Original url={current.url} label="查看视频原文件" /></div>
      {error && <p className="error" role="alert">视频无法播放，请打开原文件。</p>}
    </> : <div className="video-placeholder">视频区域</div>}
  </section>;
}
