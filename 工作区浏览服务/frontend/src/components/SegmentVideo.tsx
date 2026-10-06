import { useState } from 'react';
import type { SegmentVideo as VideoItem } from '../api';
import { Original } from '../components';

const candidateLabel = (number: number) => {
  const digits = '零一二三四五六七八九';
  return '候选' + (number < 10 ? digits[number] : number < 100
    ? (number < 20 ? '' : digits[Math.floor(number / 10)]) + '十' + (number % 10 ? digits[number % 10] : '') : number);
};

export function SegmentVideo({ items }: { items: VideoItem[] }) {
  const [stage, setStage] = useState('');
  const [selected, setSelected] = useState('');
  const [error, setError] = useState(false);
  const versions = items.filter(item => item.stage === stage).sort((a, b) => Number(b.approved) - Number(a.approved) || a.candidateNumber - b.candidateNumber);
  const current = versions.find(item => item.key === selected);
  const label = (item: VideoItem) => item.approved ? '正式版' : candidateLabel(item.candidateNumber);
  return <section className="segment-video" aria-label="视频区域">
    <div className="video-selectors tabs tabs-grouped">
      <select className="tab-select" aria-label="处理阶段" data-active={Boolean(stage)} value={stage} onChange={event => { setStage(event.target.value); setSelected(''); setError(false); }}>
        <option value="">不选择</option>
        {['一采', '二采', '后处理'].map(value => <option key={value} value={value}>{value}</option>)}
      </select>
      <select className="tab-select" aria-label="版本切换" data-active={Boolean(current)} value={current?.key || ''} onChange={event => { setSelected(event.target.value); setError(false); }}>
        <option value="" disabled hidden>版本切换</option>
        <option value="">不选择</option>
        {versions.map(item => <option key={item.key} value={item.key}>{label(item)}</option>)}
      </select>
    </div>
    {current ? <>
      <video key={current.key} controls preload="metadata" src={current.url} aria-label={`${label(current)} ${current.run} ${current.stage}`} onError={() => setError(true)} />
      <div className="video-source"><span>{current.approved ? '正式版 · 原' : ''}{candidateLabel(current.candidateNumber)} · {current.run} · {current.stage}</span><Original url={current.url} label="查看视频原文件" /></div>
      {error && <p className="error" role="alert">视频无法播放，请打开原文件。</p>}
    </> : <div className="video-placeholder">视频区域</div>}
  </section>;
}
