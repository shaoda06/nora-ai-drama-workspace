import { PointerTooltip } from './PointerTooltip';
import type { FileItem } from '../api';

export function EpisodeButton({ item, onSelect }: { item: FileItem; onSelect: (episode: string) => void }) {
  const title = item.title || (item.name === '片头' || item.name === '片尾' ? '全剧通用' : '题名未记录');
  const status = item.statusHtml?.match(/^<span class="status-badge.*?<\/span>/s)?.[0] || '';
  const titleTone = item.titleStatus === '最终定名' ? 'status-green' : item.titleStatus === '临时集名' ? 'status-orange' : 'status-gray';
  return <button className="episode-button" data-episode={item.name} onClick={() => onSelect(item.name)}>
    <strong>{item.name}</strong><PointerTooltip text={title}><span className="episode-button-title" >{title}</span></PointerTooltip>
    {item.titleStatus && <PointerTooltip text={item.titleStatus === '临时集名' ? '临时集名，尚未最终定名' : item.titleStatus}><span className={`episode-title-status ${titleTone}`}>{item.titleStatus}</span></PointerTooltip>}
    <PointerTooltip text={status.replace(/<[^>]+>/g, '')}><span className="episode-button-status"  dangerouslySetInnerHTML={{ __html: status }} /></PointerTooltip>
  </button>;
}
