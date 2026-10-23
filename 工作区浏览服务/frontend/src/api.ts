export async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error((await response.text()) || `读取失败（${response.status}）`);
  return response.json();
}
export const projectUrl = (name: string) => `/api/projects/${encodeURIComponent(name)}`;
export const styleUrl = (path: string) => `/api/krea2/files/${path.split('/').map(encodeURIComponent).join('/')}`;
export interface GenerationContext {
  scriptHtml: string; scriptUrl?: string; source?: string; issues: string[];
  shots: { id: string; duration: number | null; html: string }[];
  prompts: { english: string; chinese: string; englishUrl?: string; chineseUrl?: string };
  references: Record<'common' | 'segment', { name: string; label: string; kind: 'image' | 'video' | 'audio'; url?: string; missing?: boolean }[]>;
}
// One recorded revision/stage; url and fileRevision are empty until a video exists.
export interface SegmentVideo { key: string; url: string; run: string; stage: string; approved: boolean; candidateNumber: number; context?: GenerationContext; fileRevision: string; deliveryStatus: string; taskStatus: string; taskStateUrl?: string; checkedAt: string }
export interface SceneRound { number: number; created_at: string; note?: string; script: (FileItem & { version: string }) | null; storyboard: (FileItem & { version: string }) | null; issues: string[]; segments: { id: string; duration: number; stage: string; run: string; scriptHtml: string; scriptUrl: string }[] }
export type DirectorSheetImage = FileItem & { page: number; version: string; sourceVersion: string; candidateNumber?: number | null; adopted?: boolean };
export interface DirectorSheets { formal: DirectorSheetImage[]; candidates: DirectorSheetImage[]; record: FileItem | null }
export interface FileItem { version?: string; directorSheets?: Record<string, DirectorSheets>; storyboardIndex?: FileItem | null; generationPlan?: FileItem | null; videoPrompts?: FileItem[]; materials?: FileItem[]; materialRecord?: FileItem | null; sceneRounds?: Record<string, SceneRound[]>; warnings?: string[]; previousEpisode?: FileItem | null; kind: string; name: string; title?: string; titleStatus?: string; productionComplete?: boolean; scenes?: string[]; productionIssues?: { key: string; message: string; scene?: string }[]; script?: FileItem | null; storyboards?: Record<string, FileItem>; segments?: Record<string, { id: string; duration: number; historical?: boolean; scriptHtml: string; scriptUrl?: string; videos: SegmentVideo[] }[]>; key?: string; url?: string; children?: FileItem[]; files?: FileItem[]; summary?: string; category?: string; statusHtml?: string; approvalHtml?: string; sourceHtml?: string; duration?: string; media?: FileItem; doc?: Record<string, unknown>; prompts?: { english?: string; chinese?: string }; }
export interface Group { name: string; files: FileItem[] }
// Source records contain stage-specific fields; retain their original keys and text.
export type RecordData = Record<string, any>;

export function searchTree(items: FileItem[], search: string): FileItem[] {
  if (!search) return items;
  return items.flatMap(item => {
    if ((item.name + (item.summary || '')).toLowerCase().includes(search.toLowerCase())) return [item];
    const children = searchTree(item.children || item.files || [], search);
    return children.length ? [{ ...item, children, files: undefined }] : [];
  });
}
