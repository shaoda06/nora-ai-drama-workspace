import type { FileItem, SceneRound } from './api';

export function newVideoSegmentsForRound(segments: NonNullable<FileItem['segments']>[string], rounds: SceneRound[], selectedRound?: number) {
  const current = rounds.find(round => round.number === selectedRound);
  return new Set((current?.segments || []).filter(entry =>
    segments.find(segment => segment.id === entry.id)?.videos.some(video => video.stage === entry.stage && video.run === entry.run && video.url)
    && !rounds.some(round => round.number < current!.number
      && round.segments.some(previous => previous.id === entry.id && previous.stage === entry.stage && previous.run === entry.run))
  ).map(entry => entry.id));
}
