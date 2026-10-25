import { PointerTooltip } from './PointerTooltip';
import type { FileItem } from '../api';

export function EpisodeTitleStatus({ status }: { status: FileItem['titleStatus'] }) {
  if (!status) return null;
  const tone = status === '最终定名' ? 'status-green' : status === '临时集名' ? 'status-orange' : 'status-gray';
  return <PointerTooltip text={status === '临时集名' ? '临时集名，尚未最终定名' : status}><span className={`episode-title-status ${tone}`}>{status}</span></PointerTooltip>;
}
