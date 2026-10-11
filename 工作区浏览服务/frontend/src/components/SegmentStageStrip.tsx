import type { CSSProperties } from 'react';
import type { FileItem, SegmentVideo } from '../api';
import './SegmentStageStrip.css';

const stages = ['一采', '二采', '后处理'];

export function segmentStageStatus(videos: SegmentVideo[], stage: string) {
  const recorded = videos.filter(video => video.stage === stage);
  const adopted = recorded.find(video => video.approved);
  if (adopted) return { state: 'adopted', symbol: '✓', detail: `${stage}：已采纳（${adopted.run}）` };
  if (!recorded.length) return { state: 'not-started', symbol: '○', detail: `${stage}：未开始` };
  const latest = recorded.reduce((last, video) => Number(video.run.slice(1)) > Number(last.run.slice(1)) ? video : last);
  const details = latest.taskStatus && latest.taskStatus !== '未记录' ? [latest.taskStatus] : [];
  if (latest.url) details.push('已有候选，尚未采纳');
  else if (latest.deliveryStatus?.startsWith('取回失败')) details.push('取回失败');
  else if (latest.deliveryStatus?.startsWith('未取回')) details.push('未取回');
  return { state: 'started', symbol: '−', detail: `${stage}：${latest.run} · ${details.join('；') || '资料准备中，尚未完成'}` };
}

export function SegmentStageStrip({ segments, selected, onSelect }: {
  segments: NonNullable<FileItem['segments']>[string]; selected: string; onSelect: (id: string) => void;
}) {
  return <div className="segment-scroll segment-progress-scroll">
    <div className="segment-timeline" style={{ '--segment-columns': segments.map(item => `minmax(84px, ${item.duration}fr)`).join(' '), '--segment-count': segments.length } as CSSProperties}>
      <div className="segment-strip" role="group" aria-label="本场分段">
        {segments.map(item => <button key={item.id} aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} title={`${item.id} · 计划时长 ${item.duration}秒`} aria-pressed={item.id === selected} onClick={() => onSelect(item.id)}><span>{item.id}</span><span>{item.duration}秒</span></button>)}
      </div>
      <div className="segment-stage-strip" role="group" aria-label="分段制作进度：一采、二采、后处理">
        {segments.map(item => <div className="segment-stage-cell" key={item.id} data-segment={item.id} data-selected={item.id === selected}>
          {stages.map(stage => {
            const status = segmentStageStatus(item.videos, stage);
            const label = `${item.id} ${status.detail}`;
            return <span key={stage} className={`segment-stage-icon is-${status.state}`} role="img" aria-label={label} title={label} tabIndex={0}>{status.symbol}</span>;
          })}
        </div>)}
      </div>
    </div>
  </div>;
}
