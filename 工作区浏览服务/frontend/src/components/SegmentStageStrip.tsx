import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import type { FileItem, SegmentVideo } from '../api';
import { PointerTooltip } from './PointerTooltip';
import type { PreviousEpisodeEnding } from '../previousEpisodeEnding';
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

export function SegmentStageStrip({ segments, selected, onSelect, vertical = false, previousEnding, previousSelected, onPreviousSelect }: {
  segments: NonNullable<FileItem['segments']>[string]; selected: string; vertical?: boolean; onSelect: (id: string) => void;
  previousEnding: PreviousEpisodeEnding | null; previousSelected: boolean; onPreviousSelect: () => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!vertical) return;
    const active = rail.current!.querySelector<HTMLElement>('[data-selected="true"]')!;
    const scroller = rail.current!.parentElement!;
    const offset = active.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
    if (offset < 0 || offset + active.offsetHeight > scroller.clientHeight) scroller.scrollTop += offset;
  }, [selected, vertical]);
  const previousAvailable = previousEnding?.segment?.videos.some(video => video.url);
  const previousButton = previousEnding && <button className="previous-ending-button" data-selected={previousSelected}
    aria-label={`查看${previousEnding.episode}上集末段`} aria-pressed={previousSelected} disabled={!previousAvailable} onClick={onPreviousSelect}>
    <strong>上集末段</strong><span>{previousEnding.episode}{previousEnding.segment ? ` · ${previousEnding.segment.id}` : ''}</span>
    <small>{previousAvailable ? `${previousEnding.scene} · ${previousEnding.segment!.duration}秒` : previousEnding.segment ? '暂无可播放视频' : '暂无分段资料'}</small>
  </button>;
  if (vertical) return <div ref={rail} className="segment-vertical-strip" role="group" aria-label="本场分段">
    {previousButton}
    {segments.map(item => <div className="segment-vertical-item" key={item.id} data-selected={item.id === selected}>
      <PointerTooltip text={`${item.id} · 计划时长 ${item.duration}秒`}><button aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} aria-pressed={item.id === selected} onClick={() => onSelect(item.id)}><span>{item.id}</span><span>{item.duration}秒</span></button></PointerTooltip>
      <div className="segment-stage-cell" data-segment={item.id} data-selected={item.id === selected}>
        {stages.map(stage => {
          const status = segmentStageStatus(item.videos, stage);
          const label = `${item.id} ${status.detail}`;
          return <PointerTooltip key={stage} text={label}><span className={`segment-stage-icon is-${status.state}`} role="img" aria-label={label} tabIndex={0}>{status.symbol}</span></PointerTooltip>;
        })}
      </div>
    </div>)}
  </div>;
  return <div className="segment-scroll segment-progress-scroll">
    <div className={'segment-timeline' + (previousEnding ? ' has-previous-ending' : '')} style={{ '--segment-columns': segments.map(item => `minmax(84px, ${item.duration}fr)`).join(' '), '--segment-count': segments.length } as CSSProperties}>
      {previousButton}
      <div className="segment-strip" role="group" aria-label="本场分段">
        {segments.map(item => <PointerTooltip key={item.id} text={`${item.id} · 计划时长 ${item.duration}秒`}><button  aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`}  aria-pressed={item.id === selected} onClick={() => onSelect(item.id)}><span>{item.id}</span><span>{item.duration}秒</span></button></PointerTooltip>)}
      </div>
      <div className="segment-stage-strip" role="group" aria-label="分段制作进度：一采、二采、后处理">
        {segments.map(item => <div className="segment-stage-cell" key={item.id} data-segment={item.id} data-selected={item.id === selected}>
          {stages.map(stage => {
            const status = segmentStageStatus(item.videos, stage);
            const label = `${item.id} ${status.detail}`;
            return <PointerTooltip key={stage} text={label}><span className={`segment-stage-icon is-${status.state}`} role="img" aria-label={label} tabIndex={0}>{status.symbol}</span></PointerTooltip>;
          })}
        </div>)}
      </div>
    </div>
  </div>;
}
