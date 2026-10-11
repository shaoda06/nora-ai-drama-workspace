import { PointerTooltip } from './PointerTooltip';
import type { FileItem } from '../api';

export function EpisodeButton({ item, onSelect }: { item: FileItem; onSelect: (episode: string) => void }) {
  const title = item.title || '题名未记录';
  const status = item.statusHtml?.match(/^<span class="status-badge.*?<\/span>/s)?.[0] || '';
  return <button className="episode-button" data-episode={item.name} onClick={() => onSelect(item.name)}>
    <strong>{item.name}</strong><PointerTooltip text={title}><span className="episode-button-title" >{title}</span></PointerTooltip>
    <PointerTooltip text={status.replace(/<[^>]+>/g, '')}><span className="episode-button-status"  dangerouslySetInnerHTML={{ __html: status }} /></PointerTooltip>
  </button>;
}
