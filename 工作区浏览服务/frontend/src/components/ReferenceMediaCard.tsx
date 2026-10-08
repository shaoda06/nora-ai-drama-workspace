import type { FileItem } from '../api';
import { Rich } from '../components';
import { AudioPreviewButton } from './AudioPreviewButton';

export function ReferenceMediaCard({ item, audio, playing, progress, onPlay, onSelect }: {
  item: FileItem; audio: boolean; playing: boolean; progress: number; onPlay: () => void; onSelect: () => void;
}) {
  const title = item.media?.name || item.name;
  return <article className="reference-media-card" onClick={onSelect}>
    <button className="link reference-media-title" title={title} onClick={event => { event.stopPropagation(); onSelect(); }}>{title}</button>
    <span className="reference-media-control" onClick={event => event.stopPropagation()}>{audio ? <AudioPreviewButton name={item.name} enabled={!!item.media} playing={playing} progress={progress} onClick={onPlay} /> : <button className="voice-preview" aria-label={`查看${item.name}视频`} disabled={!item.media} onClick={onSelect}>▶</button>}</span>
    <Rich html={item.approvalHtml} />
  </article>;
}
