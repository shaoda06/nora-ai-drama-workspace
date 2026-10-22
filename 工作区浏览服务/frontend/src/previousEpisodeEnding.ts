import type { FileItem } from './api';

export const PREVIOUS_ENDING = '@previous-ending';
export type ProductionSegment = NonNullable<FileItem['segments']>[string][number];
export interface PreviousEpisodeEnding {
  episode: string;
  scene: string;
  segment?: ProductionSegment;
  segments: ProductionSegment[];
}

export function previousEpisodeEnding(episodes: FileItem[], episode: string): PreviousEpisodeEnding | null {
  if (episode === '片头' || episode === '片尾') return null;
  const number = Number(episode.slice(2));
  if (number === 1) return null;
  const previous = `EP${String(number - 1).padStart(episode.length - 2, '0')}`;
  const item = episodes.find(item => item.name === previous);
  const scene = item?.scenes?.at(-1) || '';
  const segments = item?.segments?.[scene] || [];
  return { episode: previous, scene, segments, segment: segments.at(-1) };
}
