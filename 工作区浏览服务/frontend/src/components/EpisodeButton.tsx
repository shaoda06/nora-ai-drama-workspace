import { EpisodeTitleStatus } from './EpisodeTitleStatus';
import { PointerTooltip } from './PointerTooltip';
import type { FileItem } from '../api';
import './EpisodeButton.css';

export function EpisodeButton({ item, onSelect, duration }: { item: FileItem; onSelect: (episode: string) => void; duration?: string }) {
  const title = item.title || (item.name === '片头' || item.name === '片尾' ? '全剧通用' : '题名未记录');
  const status = item.statusHtml?.match(/^<span class="status-badge.*?<\/span>/s)?.[0] || '';
  return <button className={'episode-button' + (duration === undefined ? '' : ' episode-button-with-duration')} data-episode={item.name} onClick={() => onSelect(item.name)}>
    <span className="episode-button-main"><strong>{item.name}</strong><PointerTooltip text={title}><span className="episode-button-title" >{title}</span></PointerTooltip>
      <EpisodeTitleStatus status={item.titleStatus} />
    </span>
    <span className={'episode-button-meta' + (duration === undefined ? '' : ' episode-button-meta-with-duration')}>
      {duration !== undefined && <PointerTooltip text="最新轮次时长；* 表示含计划时长"><span className="episode-button-duration">{duration}</span></PointerTooltip>}
      <PointerTooltip text={status.replace(/<[^>]+>/g, '')}><span className="episode-button-status" dangerouslySetInnerHTML={{ __html: status }} /></PointerTooltip>
    </span>
  </button>;
}
