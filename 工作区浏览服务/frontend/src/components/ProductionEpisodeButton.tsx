import { useQuery } from '@tanstack/react-query';
import { get, projectUrl, type FileItem } from '../api';
import { EpisodeButton } from './EpisodeButton';
import { FloatingMessage } from './Notifications';
import { formatProductionDuration, sceneDurationEntries, useEpisodeDurations } from './useEpisodeDurations';

// Visible production entries only. Share episode details and media metadata with the detail page.
export function ProductionEpisodeButton({ item, project, revision, onSelect }: {
  item: FileItem; project: string; revision: number; onSelect: (episode: string) => void;
}) {
  const detail = useQuery({ queryKey: ['episode', project, item.name, revision],
    queryFn: () => get<FileItem>(`${projectUrl(project)}/episodes/${item.name}`) });
  const episode = detail.data;
  const latest = episode?.episodeRounds?.at(-1);
  const entries = Object.fromEntries((latest?.scenes || episode?.scenes || []).map(scene => [scene,
    sceneDurationEntries(episode!, scene, latest?.number ?? episode?.sceneRounds?.[scene]?.at(-1)?.number)]));
  const durations = useEpisodeDurations(entries);
  return <>
    <EpisodeButton item={item} onSelect={onSelect} duration={detail.isPending ? '读取中…' : detail.isError ? '时长读取失败' : formatProductionDuration(durations.total)} />
    {detail.isError ? <FloatingMessage tone="error">{item.name}时长读取失败：{detail.error.message}。<button className="link" onClick={() => void detail.refetch()}>重新读取</button></FloatingMessage>
      : durations.failed > 0 && <FloatingMessage tone="error">{item.name}有{durations.failed}段视频时长读取失败，暂用计划时长（*）。<button className="link" onClick={durations.retry}>重新读取</button></FloatingMessage>}
  </>;
}
