import type { FileItem } from '../api';

export function EpisodeButton({ item, onSelect }: { item: FileItem; onSelect: (episode: string) => void }) {
  const title = item.title || '题名未记录';
  const status = item.statusHtml?.match(/^<span class="status-badge.*?<\/span>/s)?.[0] || '';
  return <button className="episode-button" data-episode={item.name} onClick={() => onSelect(item.name)}>
    <strong>{item.name}</strong><span className="episode-button-title" title={title}>{title}</span>
    <span className="episode-button-status" title={status.replace(/<[^>]+>/g, '')} dangerouslySetInnerHTML={{ __html: status }} />
  </button>;
}
