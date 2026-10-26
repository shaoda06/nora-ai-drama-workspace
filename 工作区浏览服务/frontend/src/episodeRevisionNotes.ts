import type { SegmentVideo } from './api';
import type { NoteInput, OverallNote, SavedSceneNotes } from './revisionNotes';
import { noteKey } from './revisionNotes';
import { candidateLabel } from './components/SegmentVideo';

export interface EpisodeReview {
  number?: number;
  rounds: number[];
  scenes: { id: string; number?: number; segments: { id: string; videos: SegmentVideo[] }[];
    versions: { id: string; stage: string; run: string }[] }[];
}
export interface SavedEpisodeNotes { episode: string; scenes: Record<string, SavedSceneNotes>; rounds: Record<string, OverallNote> }
export type EpisodeExportNote = NoteInput & { scene: string; key: string; title: string; original: string; current: boolean; editable: boolean };

export function episodeExportNotes(saved: SavedEpisodeNotes, review: EpisodeReview): EpisodeExportNote[] {
  const scenes = [...new Set([...review.scenes.map(item => item.id), ...Object.keys(saved.scenes)])]
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  return scenes.flatMap(scene => {
    const selected = review.scenes.find(item => item.id === scene);
    const ids = selected?.versions.map(item => item.id) || selected?.segments.map(item => item.id) || [];
    const order = (id: string) => { const index = ids.indexOf(id); return index < 0 ? ids.length + Number(id.slice(1)) : index; };
    return Object.values(saved.scenes[scene]?.notes || {}).filter(note => note.text.trim())
      .sort((a, b) => order(a.segment) - order(b.segment) || (a.roundNumber ?? 0) - (b.roundNumber ?? 0)
        || ['一采', '二采', '后处理'].indexOf(a.stage) - ['一采', '二采', '后处理'].indexOf(b.stage) || Number(b.run.slice(1)) - Number(a.run.slice(1)))
      .map(note => {
        const video = selected?.segments.find(item => item.id === note.segment)?.videos.find(item => item.stage === note.stage && item.run === note.run);
        const candidate = video ? candidateLabel(video.candidateNumber, video.approved) : '候选号未登记';
        const current = !!selected && (note.roundNumber ?? null) === (selected.number ?? null)
          && selected.versions.some(item => item.id === note.segment && item.stage === note.stage && item.run === note.run);
        const editable = review.rounds.includes(note.roundNumber!);
        return { ...note, scene, key: scene + '/' + noteKey(note), current, editable,
          title: `${scene} / ${note.roundNumber ? `第${note.roundNumber}轮` : '未标注轮次'} / ${note.segment} / ${note.stage} / ${note.run} / ${candidate}${editable ? '' : ' / 场次历史（只读）'}`, original: note.text };
      });
  });
}

// Arrange timestamped shot blocks for copying; the saved original stays untouched.
export function shotOrderedText(text: string): string {
  const blocks = text.split(/(?=^(?:\d{2}\.\d{2}\.\d秒[，,]\s*)?SH\d+\s*[：:])/m);
  const identity = (block: string) => block.match(/^(?:(\d{2})\.(\d{2})\.(\d)秒[，,]\s*)?SH(\d+)\s*[：:]/);
  const prefix = blocks[0] && !identity(blocks[0]) ? blocks.shift()! : '';
  blocks.sort((a, b) => {
    const first = identity(a)!, second = identity(b)!;
    return Number(first[4]) - Number(second[4])
      || (Number(first[1] || 0) * 600 + Number(first[2] || 0) * 10 + Number(first[3] || 0))
      - (Number(second[1] || 0) * 600 + Number(second[2] || 0) * 10 + Number(second[3] || 0));
  });
  return [prefix.trimEnd(), ...blocks.map(block => block.trimEnd())].filter(Boolean).join('\n');
}
